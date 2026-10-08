"""Runtime evidence collector for assembling verifiable chat-evidence packages.

Tracks accessed conclusions, source message references, and tool executions
to produce audit-ready evidence for transparent agent responses.
"""

from __future__ import annotations

from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.conclusion_attribution.models import (
    AttributedConclusion,
    ChatEvidence,
    MessageReference,
    ToolCallRecord,
)


class EvidenceCollector:
    """Session-scoped runtime evidence collector."""

    def __init__(self, session_id: str | None = None) -> None:
        self.session_id: str | None = session_id
        self._conclusions: dict[str, AttributedConclusion] = {}
        self._messages: list[MessageReference] = []
        self._tool_calls: list[ToolCallRecord] = []
        self._reasoning_trace_id: str | None = None

    def set_trace_id(self, trace_id: str) -> None:
        """Bind an active reasoning trace ID."""
        self._reasoning_trace_id = trace_id

    def record_conclusion_access(self, conclusion: AttributedConclusion) -> None:
        """Record a conclusion that was referenced or activated during reasoning."""
        self._conclusions[conclusion.id] = conclusion

    def record_conclusions(self, conclusions: Sequence[AttributedConclusion]) -> None:
        """Record multiple conclusions."""
        for c in conclusions:
            self._conclusions[c.id] = c

    def record_message_reference(
        self,
        message_id: str,
        session_id: str,
        snippet: str,
        role: str = "user",
        timestamp: str | None = None,
    ) -> None:
        """Record an explicit source chat message that justifies the agent assertion."""
        # Avoid redundant duplicate message references
        if any(m.message_id == message_id for m in self._messages):
            return

        self._messages.append(
            MessageReference(
                message_id=message_id,
                session_id=session_id,
                role=role,
                snippet=snippet,
                timestamp=timestamp,
            )
        )

    def record_tool_call(
        self,
        tool_name: str,
        tool_input: dict[str, str],
        tool_output_snippet: str = "",
    ) -> None:
        """Record an invoked tool execution providing empirical ground truth."""
        self._tool_calls.append(
            ToolCallRecord(
                tool_name=tool_name,
                tool_input=tool_input,
                tool_output_snippet=tool_output_snippet,
            )
        )

    def assemble(self) -> ChatEvidence:
        """Assemble collected items into a frozen ChatEvidence package."""
        return ChatEvidence(
            conclusions=list(self._conclusions.values()),
            messages=list(self._messages),
            tool_calls=list(self._tool_calls),
            reasoning_trace_id=self._reasoning_trace_id,
        )

    def clear(self) -> None:
        """Reset internal buffers for a clean turn."""
        self._conclusions.clear()
        self._messages.clear()
        self._tool_calls.clear()
        self._reasoning_trace_id = None
