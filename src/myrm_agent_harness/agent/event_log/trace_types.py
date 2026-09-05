"""Execution trace types — task-level aggregation of structured events.

Provides a read-side view that reconstructs the complete execution flow
(input → tool calls → intermediate states → errors → output) from the
append-only event stream.  Used by downstream systems:

- Frontend task replay timeline
- Skill Evolution scoring (task_input + agent_output)
- Memory extraction (successful tool call patterns)
- Analytics dimension slicing (user_id, agent_id, task_type)

[INPUT]
- event_log.types::StructuredEvent (POS: Single source of truth for event log data structures)

[OUTPUT]
- ToolCallRecord: single tool invocation with timing and outcome
- ExecutionTrace: complete task-level execution view
- TraceMetadata: context dimensions extracted from event data

[POS]
Read-side aggregation types.  Constructed by trace_builder from raw events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TraceOutcome(StrEnum):
    """Task execution outcome."""

    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TraceMetadata:
    """Context dimensions extracted from event data ``_``-prefixed keys."""

    user_id: str | None = None
    agent_id: str | None = None
    task_type: str | None = None
    trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    """Single tool invocation with timing and outcome."""

    sequence: int
    tool_name: str
    start_time: float
    end_time: float | None = None
    duration_ms: float | None = None
    success: bool = True
    error: str | None = None
    tool_call_id: str | None = None
    message_id: str | None = None
    input_data: dict[str, object] = field(default_factory=dict)
    output_summary: str | None = None
    output_data: str | dict[str, object] | list[object] | None = None
    fault_side: str | None = None  # Deterministic attribution (FaultSide enum value)


@dataclass(frozen=True, slots=True)
class LLMCallRecord:
    """Single LLM invocation with timing and token usage."""

    sequence: int
    start_time: float
    end_time: float | None = None
    model_name: str | None = None
    prompt_preview: str | None = None
    message_count: int = 0
    duration_ms: float | None = None
    ttft_ms: float | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass(slots=True)
class ExecutionTrace:
    """Complete task-level execution view.

    Aggregates all StructuredEvents for a session into a structured
    timeline suitable for replay, scoring, and pattern extraction.
    """

    session_id: str
    metadata: TraceMetadata = field(default_factory=TraceMetadata)
    outcome: TraceOutcome = TraceOutcome.UNKNOWN

    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0

    task_input: str = ""
    output: str = ""

    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    llm_calls: list[LLMCallRecord] = field(default_factory=list)
    errors: list[dict[str, object]] = field(default_factory=list)
    human_feedback: list[dict[str, object]] = field(default_factory=list)
    first_irrecoverable_index: int | None = None
    first_irrecoverable_timestamp: float | None = None

    total_events: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "metadata": {
                "user_id": self.metadata.user_id,
                "agent_id": self.metadata.agent_id,
                "task_type": self.metadata.task_type,
                "trace_id": self.metadata.trace_id,
            },
            "outcome": self.outcome.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "task_input": self.task_input,
            "output": self.output,
            "tool_calls": [
                {
                    "sequence": tc.sequence,
                    "tool_name": tc.tool_name,
                    "start_time": tc.start_time,
                    "end_time": tc.end_time,
                    "duration_ms": tc.duration_ms,
                    "success": tc.success,
                    "error": tc.error,
                    "tool_call_id": tc.tool_call_id,
                    "message_id": tc.message_id,
                    "input_data": tc.input_data,
                    "output_summary": tc.output_summary,
                    "output_data": tc.output_data,
                    "fault_side": tc.fault_side,
                }
                for tc in self.tool_calls
            ],
            "llm_calls": [
                {
                    "sequence": lc.sequence,
                    "start_time": lc.start_time,
                    "end_time": lc.end_time,
                    "model_name": lc.model_name,
                    "prompt_preview": lc.prompt_preview,
                    "message_count": lc.message_count,
                    "duration_ms": lc.duration_ms,
                    "ttft_ms": lc.ttft_ms,
                    "prompt_tokens": lc.prompt_tokens,
                    "completion_tokens": lc.completion_tokens,
                    "total_tokens": lc.total_tokens,
                    "cache_read_tokens": lc.cache_read_tokens,
                }
                for lc in self.llm_calls
            ],
            "errors": self.errors,
            "human_feedback": self.human_feedback,
            "first_irrecoverable_index": self.first_irrecoverable_index,
            "first_irrecoverable_timestamp": self.first_irrecoverable_timestamp,
            "total_events": self.total_events,
            "total_tokens": self.total_tokens,
            "prompt_tokens": sum(lc.prompt_tokens for lc in self.llm_calls),
            "completion_tokens": sum(lc.completion_tokens for lc in self.llm_calls),
            "cache_read_tokens": sum(lc.cache_read_tokens for lc in self.llm_calls),
            "cache_hit_ratio": (
                round(sum(lc.cache_read_tokens for lc in self.llm_calls) / sum(lc.prompt_tokens for lc in self.llm_calls), 4)
                if sum(lc.prompt_tokens for lc in self.llm_calls) > 0
                else 0.0
            ),
        }
