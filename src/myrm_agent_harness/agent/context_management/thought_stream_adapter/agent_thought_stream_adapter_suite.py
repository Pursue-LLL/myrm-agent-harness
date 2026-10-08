"""Comprehensive facade suite for agent thought streaming and dual-mode external client bridging.

[INPUT]
- ClientCapabilityNegotiator: Adaptive negotiation for target reasoning mode.
- LongReasoningHeartbeatConduit: Resilience conduit emitting keep-alive events.
- ThoughtAdapterConfig, ThoughtStepDescriptor, ThoughtStreamChunk: Contracts and domain models.

[OUTPUT]
- AgentThoughtStreamAdapterSuite: Unified facade managing lifecycle, stateful tags, and chunk routing.

[POS]
Main entry point for external OpenAI-compatible streaming bridge and thinking telemetry.
"""

from __future__ import annotations

import time
from typing import Mapping

from .agent_thought_normalizer import AgentThoughtNormalizer
from .client_capability_negotiator import ClientCapabilityNegotiator
from .long_reasoning_heartbeat_conduit import LongReasoningHeartbeatConduit
from .thought_adapter_types import (
    ClientReasoningMode,
    ThoughtActionType,
    ThoughtAdapterConfig,
    ThoughtStepDescriptor,
    ThoughtStreamChunk,
)


class AgentThoughtStreamAdapterSuite:
    """Unified facade managing intermediate cognition streaming and dual-mode protocol delivery."""

    def __init__(
        self,
        config: ThoughtAdapterConfig | None = None,
        initial_mode: ClientReasoningMode | None = None,
    ) -> None:
        self._config = config or ThoughtAdapterConfig()
        self._normalizer = AgentThoughtNormalizer(self._config)
        self._negotiator = ClientCapabilityNegotiator(self._config)
        self._heartbeat_conduit = LongReasoningHeartbeatConduit(self._config)

        self._active_mode: ClientReasoningMode = initial_mode or self._config.default_mode
        self._is_think_tag_open: bool = False
        self._has_started_final_content: bool = False
        self._active_steps: dict[str, ThoughtStepDescriptor] = {}

    @property
    def active_mode(self) -> ClientReasoningMode:
        """The currently active streaming mode."""
        return self._active_mode

    @property
    def is_think_tag_open(self) -> bool:
        """Whether a fallback <think> tag is currently unclosed in the stream."""
        return self._is_think_tag_open

    def negotiate_client_mode(
        self,
        user_agent: str | None = None,
        headers: Mapping[str, str] | None = None,
        request_params: Mapping[str, str | bool | int] | None = None,
    ) -> ClientReasoningMode:
        """Dynamically detect and activate the best reasoning mode for the calling client."""
        self._active_mode = self._negotiator.negotiate(
            user_agent=user_agent,
            headers=headers,
            request_params=request_params,
        )
        return self._active_mode

    def start_step(
        self,
        step_id: str,
        action_type: ThoughtActionType,
        title: str,
        metadata: Mapping[str, str] | None = None,
        start_time: float | None = None,
    ) -> list[ThoughtStreamChunk]:
        """Signal the start of a cognitive or tool action, returning formatted opening chunks."""
        descriptor = ThoughtStepDescriptor(
            step_id=step_id,
            action_type=action_type,
            title=title,
            metadata=metadata or {},
        )
        self._active_steps[step_id] = descriptor
        self._normalizer.record_step_start(step_id, start_time)

        if self._active_mode == ClientReasoningMode.SILENT:
            return []

        header_text = self._normalizer.format_step_header(descriptor)
        chunks: list[ThoughtStreamChunk] = []

        if self._active_mode == ClientReasoningMode.THINK_TAG_FALLBACK:
            if not self._is_think_tag_open:
                chunks.append(
                    ThoughtStreamChunk(
                        chunk_type="content",
                        text=self._config.think_tag_open,
                    )
                )
                self._is_think_tag_open = True
            if header_text:
                chunks.append(
                    ThoughtStreamChunk(
                        chunk_type="content",
                        text=header_text,
                        step_id=step_id,
                    )
                )
        else:
            if header_text:
                chunks.append(
                    ThoughtStreamChunk(
                        chunk_type="reasoning_content",
                        text=header_text,
                        step_id=step_id,
                    )
                )

        self._heartbeat_conduit.mark_activity()
        return chunks

    def stream_step_chunk(self, step_id: str, text: str) -> list[ThoughtStreamChunk]:
        """Emit incremental thinking or execution delta for an active step."""
        if not text or self._active_mode == ClientReasoningMode.SILENT:
            return []

        self._heartbeat_conduit.mark_activity()
        if self._active_mode == ClientReasoningMode.THINK_TAG_FALLBACK:
            return [ThoughtStreamChunk(chunk_type="content", text=text, step_id=step_id)]
        return [ThoughtStreamChunk(chunk_type="reasoning_content", text=text, step_id=step_id)]

    def finish_step(
        self,
        step_id: str,
        status: str = "completed",
        summary: str = "",
        elapsed_ms: float | None = None,
    ) -> list[ThoughtStreamChunk]:
        """Complete an active step and emit its completion summary and timings."""
        descriptor = self._active_steps.pop(step_id, None)
        if descriptor is None:
            descriptor = ThoughtStepDescriptor(
                step_id=step_id,
                action_type=ThoughtActionType.THINKING,
                title="Operation",
            )

        if self._active_mode == ClientReasoningMode.SILENT:
            return []

        completion_text = self._normalizer.format_step_completion(
            descriptor,
            status=status,
            summary=summary,
            elapsed_ms=elapsed_ms,
        )

        chunks: list[ThoughtStreamChunk] = []
        if self._active_mode == ClientReasoningMode.THINK_TAG_FALLBACK:
            chunks.append(ThoughtStreamChunk(chunk_type="content", text=completion_text, step_id=step_id))
        else:
            chunks.append(ThoughtStreamChunk(chunk_type="reasoning_content", text=completion_text, step_id=step_id))

        self._heartbeat_conduit.mark_activity()
        return chunks

    def transition_to_final_content(self) -> list[ThoughtStreamChunk]:
        """Close any open reasoning block before starting final assistant response content."""
        if self._has_started_final_content:
            return []

        self._has_started_final_content = True
        chunks: list[ThoughtStreamChunk] = []

        if self._active_mode == ClientReasoningMode.THINK_TAG_FALLBACK and self._is_think_tag_open:
            chunks.append(ThoughtStreamChunk(chunk_type="content", text=self._config.think_tag_close))
            self._is_think_tag_open = False

        self._heartbeat_conduit.mark_activity()
        return chunks

    def stream_final_content_chunk(self, text: str) -> list[ThoughtStreamChunk]:
        """Emit final response text chunk, guaranteeing preceding thought blocks are closed."""
        if not text:
            return []

        chunks: list[ThoughtStreamChunk] = []
        if not self._has_started_final_content:
            chunks.extend(self.transition_to_final_content())

        chunks.append(ThoughtStreamChunk(chunk_type="content", text=text))
        self._heartbeat_conduit.mark_activity()
        return chunks

    def poll_heartbeat(self, now: float | None = None) -> ThoughtStreamChunk | None:
        """Poll for silence timeout and return a keep-alive chunk if threshold reached."""
        current_time = now if now is not None else time.monotonic()
        if not self._heartbeat_conduit.should_emit_heartbeat(current_time):
            return None

        active_title: str | None = None
        if self._active_steps:
            first_step = next(iter(self._active_steps.values()))
            active_title = first_step.title

        return self._heartbeat_conduit.generate_heartbeat_chunk(
            mode=self._active_mode,
            active_step_title=active_title,
            now=current_time,
        )

    def close_stream(self) -> list[ThoughtStreamChunk]:
        """Safely finalize stream, ensuring any open tags are closed and finish chunk is emitted."""
        chunks: list[ThoughtStreamChunk] = []
        if self._active_mode == ClientReasoningMode.THINK_TAG_FALLBACK and self._is_think_tag_open:
            chunks.append(ThoughtStreamChunk(chunk_type="content", text=self._config.think_tag_close))
            self._is_think_tag_open = False

        chunks.append(ThoughtStreamChunk(chunk_type="finish", text=""))
        return chunks


AgentThoughtStreamAdapterAndExternalClientDualModeEventBridgeSuite = AgentThoughtStreamAdapterSuite
