# [INPUT]: ThoughtActionType, ThoughtAdapterConfig, ThoughtStepDescriptor
# [OUTPUT]: AgentThoughtNormalizer
# [POS]: agent/context_management/thought_stream_adapter/agent_thought_normalizer.py

"""Agent thought and action normalizer for transforming internal cognition and execution into formatted representations.

[INPUT]
- ThoughtActionType: Classification of agent step.
- ThoughtAdapterConfig: Configuration for formatting tags and length thresholds.
- ThoughtStepDescriptor: Step snapshot with title, status, and metadata.

[OUTPUT]
- AgentThoughtNormalizer: Formatter for headers, chunks, tool summaries, and step summaries.

[POS]
Intermediate translation layer between raw agent engine events and formatted external reasoning streams.
"""

from __future__ import annotations

import time
from typing import Mapping

from .thought_adapter_types import (
    ThoughtActionType,
    ThoughtAdapterConfig,
    ThoughtStepDescriptor,
)


class AgentThoughtNormalizer:
    """Normalizes raw agent cognition events into structured stream representations."""

    def __init__(self, config: ThoughtAdapterConfig | None = None) -> None:
        self._config = config or ThoughtAdapterConfig()
        self._step_start_times: dict[str, float] = {}

    def record_step_start(self, step_id: str, start_time: float | None = None) -> None:
        """Record the timestamp when a step begins for elapsed time calculation."""
        self._step_start_times[step_id] = start_time if start_time is not None else time.monotonic()

    def get_elapsed_ms(self, step_id: str, finish_time: float | None = None) -> float:
        """Compute the elapsed duration in milliseconds for a step."""
        start = self._step_start_times.get(step_id)
        if start is None:
            return 0.0
        now = finish_time if finish_time is not None else time.monotonic()
        return max(0.0, (now - start) * 1000.0)

    def format_step_header(self, step: ThoughtStepDescriptor) -> str:
        """Format an opening visual banner for a step based on its action type."""
        if not self._config.format_action_headers:
            return ""

        title = step.title.strip()
        match step.action_type:
            case ThoughtActionType.THINKING:
                return f"> 💭 [Thinking] {title}\n"
            case ThoughtActionType.PLANNING:
                return f"> 📋 [Plan] {title}\n"
            case ThoughtActionType.TOOL_EXECUTION:
                tool_name = step.metadata.get("tool_name", "")
                suffix = f" ({tool_name})" if tool_name else ""
                return f"> 🛠️ [Tool Call] {title}{suffix}\n"
            case ThoughtActionType.TOOL_RESULT:
                return f"> 📥 [Tool Result] {title}\n"
            case ThoughtActionType.OBSERVATION:
                return f"> 👁️ [Observation] {title}\n"

    def format_step_completion(
        self,
        step: ThoughtStepDescriptor,
        status: str = "completed",
        summary: str = "",
        elapsed_ms: float | None = None,
    ) -> str:
        """Format a closing confirmation banner with elapsed time and outcome."""
        actual_elapsed = elapsed_ms if elapsed_ms is not None else self.get_elapsed_ms(step.step_id)
        symbol = "✓" if status == "completed" else "✗"
        result_parts: list[str] = [f"> {symbol} [{status.upper()}] Finished in {actual_elapsed:.1f}ms"]

        if summary:
            cleaned_summary = summary.strip().replace("\n", " ")
            if len(cleaned_summary) > self._config.max_tool_summary_chars:
                cleaned_summary = cleaned_summary[: self._config.max_tool_summary_chars] + "..."
            result_parts.append(f"> Outcome: {cleaned_summary}")

        result_parts.append("\n")
        return "\n".join(result_parts)

    def truncate_tool_payload(self, payload: str) -> str:
        """Summarize and truncate verbose tool result payloads to prevent blowing up client streams."""
        trimmed = payload.strip()
        if len(trimmed) <= self._config.max_tool_summary_chars:
            return trimmed
        return trimmed[: self._config.max_tool_summary_chars] + f"... (truncated, total {len(trimmed)} chars)"
