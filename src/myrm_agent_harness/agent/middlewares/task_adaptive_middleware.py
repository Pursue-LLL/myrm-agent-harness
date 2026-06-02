"""Task-Adaptive Context Middleware.

[INPUT]
- agent.event_log.types::TraceRunDigest (POS: Single source of truth for event log data structures.)
- langchain_core.messages::HumanMessage (POS: Core message type definitions. All cross-channel communication data structures are defined here; zero I/O, pure data.)
- agent.streaming.utils::DATETIME_SYSTEM_RULES (POS: Provides hn, dumb_property_dict, dumb_css_parser.)

[OUTPUT]
- TaskAdaptiveMiddleware: Injects JIT historical evidence into the context.

[POS]
Applies execution constraints BEFORE the agent runs based on Trace Analytics.
Injects context into the last HumanMessage to strictly preserve Prompt Cache.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import BaseMessage, HumanMessage

if TYPE_CHECKING:
    from myrm_agent_harness.agent.event_log.types import TraceRunDigest

logger = logging.getLogger(__name__)


class TaskAdaptiveMiddleware(AgentMiddleware[Any, Any]):
    """Injects Just-In-Time historical evidence (Anti-patterns/Hotspots) into the context.

    CRITICAL CACHE DESIGN:
    Never inject dynamic task-adaptive content into the SystemMessage.
    Instead, append it to the last HumanMessage using <task_adaptive_context>
    to guarantee 95%+ prompt prefix cache hit rates.
    """

    # Define fields for Pydantic (AgentMiddleware inherits from BaseModel)
    trace_digest: Any = None
    _injected: bool = False

    def __init__(self, trace_digest: TraceRunDigest | None = None, **kwargs: Any) -> None:
        """Initialize with an optional TraceRunDigest provided by the Server layer.

        Args:
            trace_digest: The JIT context assembled from historical traces.
        """
        self.trace_digest = trace_digest
        self._injected = False

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse | Any:
        raise NotImplementedError("TaskAdaptiveMiddleware does not support synchronous wrap_model_call")

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelResponse:
        """Intercept the model request to inject task-adaptive context."""

        # In case the request passes mutable messages list
        new_messages = self._process_messages(list(request.messages))
        request.messages = new_messages

        return await handler(request)

    def _process_messages(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """Inject the task-adaptive context into the message sequence."""
        if not self.trace_digest:
            return messages

        # Check if already injected to avoid duplication in this middleware instance
        if self._injected:
            return messages

        # OPTIMIZATION: Only inject on the very first turn of the session (cold start).
        # If there is more than 1 HumanMessage, the agent is already engaged and
        # previous context might cause token bloat or hallucination on new code.
        human_messages = sum(1 for m in messages if isinstance(m, HumanMessage))
        if human_messages > 1:
            return messages

        evidence_lines = [
            "\n\n<task_adaptive_context>",
            "Based on historical executions for this or similar tasks, please strictly observe the following evidence to avoid repeating past mistakes:",
        ]

        has_evidence = False

        if hasattr(self.trace_digest, "hotspots") and self.trace_digest.hotspots:
            has_evidence = True
            evidence_lines.append("\n[Historical Hotspots (Frequently accessed/modified files)]")
            for hs in self.trace_digest.hotspots[:5]:
                evidence_lines.append(f"- {hs.file_path} (Reads: {hs.read_count}, Writes: {hs.write_count})")

        if hasattr(self.trace_digest, "anti_patterns") and self.trace_digest.anti_patterns:
            has_evidence = True
            evidence_lines.append("\n[CRITICAL: Anti-Patterns & Past Failures to Avoid]")
            for ap in self.trace_digest.anti_patterns[:3]:
                evidence_lines.append(f"- Failed Tool: {ap.failed_tool}")
                evidence_lines.append(f"  Error Signature: {ap.error_signature}")
                if ap.user_correction:
                    evidence_lines.append(f"  User Correction: {ap.user_correction}")

        evidence_lines.append("</task_adaptive_context>")

        if not has_evidence:
            return messages

        self._injected = True
        injection_text = "\n".join(evidence_lines)
        logger.info("Injecting Task-Adaptive Context (%d chars) into HumanMessage.", len(injection_text))

        # Find the last HumanMessage and append to it.
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                content = messages[i].content
                if isinstance(content, str):
                    messages[i] = HumanMessage(
                        content=content + injection_text, **messages[i].model_dump(exclude={"content"})
                    )
                elif isinstance(content, list):
                    # For multi-modal content
                    # We create a new list to avoid modifying the original if it's shared
                    new_content = list(content)
                    new_content.append({"type": "text", "text": injection_text})
                    messages[i] = HumanMessage(content=new_content, **messages[i].model_dump(exclude={"content"}))
                return messages

        # Fallback if no HumanMessage exists
        messages.append(HumanMessage(content=injection_text))
        return messages
