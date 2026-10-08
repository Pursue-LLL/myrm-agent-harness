# [INPUT]: ClientReasoningMode, ThoughtAdapterConfig, ThoughtStreamChunk
# [OUTPUT]: LongReasoningHeartbeatConduit
# [POS]: agent/context_management/thought_stream_adapter/long_reasoning_heartbeat_conduit.py

"""Keep-alive heartbeat conduit for preventing gateway timeouts during long reasoning or tool execution.

[INPUT]
- ClientReasoningMode: Target mode enum.
- ThoughtAdapterConfig: Configuration specifying keep-alive intervals and switches.
- ThoughtStreamChunk: Emitted streaming chunk structure.

[OUTPUT]
- LongReasoningHeartbeatConduit: Manages activity timestamps and generates zero-pollution heartbeat chunks.

[POS]
Network-resilience layer in thought streaming preventing reverse proxy 504 and stream drops.
"""

from __future__ import annotations

import time

from .thought_adapter_types import (
    ClientReasoningMode,
    ThoughtAdapterConfig,
    ThoughtStreamChunk,
)


class LongReasoningHeartbeatConduit:
    """Monitors activity silence and produces non-polluting heartbeat chunks for external clients."""

    def __init__(self, config: ThoughtAdapterConfig | None = None) -> None:
        self._config = config or ThoughtAdapterConfig()
        self._last_emit_timestamp: float = time.monotonic()

    def mark_activity(self, timestamp: float | None = None) -> None:
        """Mark that stream data has flowed, refreshing the silence timer."""
        self._last_emit_timestamp = timestamp if timestamp is not None else time.monotonic()

    def should_emit_heartbeat(self, now: float | None = None) -> bool:
        """Check if silent interval has exceeded the configured heartbeat threshold."""
        if not self._config.enable_heartbeat:
            return False
        current_time = now if now is not None else time.monotonic()
        return (current_time - self._last_emit_timestamp) >= self._config.heartbeat_interval_seconds

    def generate_heartbeat_chunk(
        self,
        mode: ClientReasoningMode,
        active_step_title: str | None = None,
        now: float | None = None,
    ) -> ThoughtStreamChunk:
        """Generate a mode-appropriate heartbeat chunk and update the activity timestamp."""
        current_time = now if now is not None else time.monotonic()
        self.mark_activity(current_time)

        if mode == ClientReasoningMode.REASONING_CONTENT:
            # Emit a subtle thought progress token without polluting the final response content
            heartbeat_text = " ."
            return ThoughtStreamChunk(
                chunk_type="reasoning_content",
                text=heartbeat_text,
                is_heartbeat=True,
            )

        # For THINK_TAG_FALLBACK and SILENT, emit standard SSE comment line (zero content impact)
        comment_text = f": keep-alive (active: {active_step_title or 'processing'})\n\n"
        return ThoughtStreamChunk(
            chunk_type="comment",
            text=comment_text,
            is_heartbeat=True,
        )
