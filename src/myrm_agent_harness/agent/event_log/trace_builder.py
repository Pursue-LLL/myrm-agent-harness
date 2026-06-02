"""Trace builder — constructs ExecutionTrace from raw event streams.

Reads events from EventLogBackend and aggregates them into a structured
ExecutionTrace for task-level replay, scoring, and pattern extraction.

[INPUT]
- event_log.protocol::EventLogBackend (POS: Protocol contract)
- event_log.types::StructuredEvent, EventFilter (POS: Single source of truth for event log data structures)
- event_log.trace_types::ExecutionTrace, (POS: Read-side aggregation types.  Constructed by trace_builder from raw events.)

[OUTPUT]
- build_trace: construct ExecutionTrace from a single session
- query_traces: batch query traces with dimension filters

[POS]
Read-side aggregation logic.  Stateless — constructs traces from event streams
on demand without caching or mutation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .trace_types import ExecutionTrace, LLMCallRecord, ToolCallRecord, TraceMetadata, TraceOutcome
from .types import EventFilter, StructuredEvent

if TYPE_CHECKING:
    from .protocols import EventLogBackend


async def build_trace(
    backend: EventLogBackend, session_id: str, *, start_sequence: int | None = None
) -> ExecutionTrace:
    """Construct an ExecutionTrace from all events in a session.

    Args:
        backend: Event log backend to read from.
        session_id: Target session.
        start_sequence: Optional sequence to start from (for incremental builds).

    Returns:
        Fully populated ExecutionTrace.
    """
    event_filter = (
        EventFilter(start_sequence=start_sequence) if start_sequence else None
    )
    events = await backend.get_events(session_id, event_filter)
    return _aggregate_events(session_id, events)


async def query_traces(
    backend: EventLogBackend,
    *,
    user_id: str | None = None,
    task_type: str | None = None,
    start_time: float | None = None,
    end_time: float | None = None,
    limit: int = 50,
) -> list[ExecutionTrace]:
    """Query and build traces across sessions with dimension filters.

    Scans all sessions and filters by metadata dimensions extracted
    from event data.  For large-scale deployments, a specialized
    backend with indexed metadata would be more efficient.

    Args:
        backend: Event log backend.
        user_id: Filter by user ID.
        task_type: Filter by task type.
        start_time: Filter sessions started after this timestamp.
        end_time: Filter sessions started before this timestamp.
        limit: Maximum number of traces to return.

    Returns:
        List of ExecutionTrace matching the filters.
    """
    session_ids = await backend.get_all_session_ids()
    traces: list[ExecutionTrace] = []

    for sid in session_ids:
        if len(traces) >= limit:
            break

        event_filter = EventFilter(start_time=start_time, end_time=end_time, limit=200)
        events = await backend.get_events(sid, event_filter)
        if not events:
            continue

        trace = _aggregate_events(sid, events)

        if user_id and trace.metadata.user_id != user_id:
            continue
        if task_type and trace.metadata.task_type != task_type:
            continue

        traces.append(trace)

    return traces


def _aggregate_events(session_id: str, events: list[StructuredEvent]) -> ExecutionTrace:
    """Aggregate raw events into an ExecutionTrace."""
    trace = ExecutionTrace(session_id=session_id)
    trace.total_events = len(events)

    pending_tools: dict[str, list[_PendingTool]] = {}
    pending_llm: list[_PendingLLMRequest] = []
    metadata_extracted = False

    for event in events:
        if not metadata_extracted:
            trace.metadata = _extract_metadata(event)
            metadata_extracted = True

        _process_event(event, trace, pending_tools, pending_llm)

    if trace.start_time and trace.end_time:
        trace.duration_ms = (trace.end_time - trace.start_time) * 1000

    if trace.errors:
        trace.outcome = TraceOutcome.FAILURE
    elif trace.end_time > 0:
        trace.outcome = TraceOutcome.SUCCESS

    return trace


class _PendingTool:
    """Tracks a tool_start waiting for its tool_end/tool_failure."""

    __slots__ = ("input_data", "sequence", "start_time", "tool_name")

    def __init__(
        self,
        sequence: int,
        tool_name: str,
        start_time: float,
        input_data: dict[str, object],
    ) -> None:
        self.sequence = sequence
        self.tool_name = tool_name
        self.start_time = start_time
        self.input_data = input_data


class _PendingLLMRequest:
    """Tracks an llm_request waiting for its token_usage completion."""

    __slots__ = ("message_count", "model_name", "prompt_preview", "sequence", "start_time")

    def __init__(
        self,
        sequence: int,
        start_time: float,
        model_name: str | None,
        prompt_preview: str | None,
        message_count: int,
    ) -> None:
        self.sequence = sequence
        self.start_time = start_time
        self.model_name = model_name
        self.prompt_preview = prompt_preview
        self.message_count = message_count


def _extract_metadata(event: StructuredEvent) -> TraceMetadata:
    """Extract context dimensions from the first event's data."""
    data = event.data
    return TraceMetadata(
        user_id=_str_or_none(data.get("_user_id")),
        agent_id=_str_or_none(data.get("_agent_id")),
        task_type=_str_or_none(data.get("_task_type")),
        trace_id=_str_or_none(data.get("_trace_id")),
    )


def _pop_pending(
    pending: dict[str, list[_PendingTool]], tool_name: str
) -> _PendingTool | None:
    """Pop the oldest pending tool by name (FIFO)."""
    queue = pending.get(tool_name)
    if not queue:
        return None
    pt = queue.pop(0)
    if not queue:
        del pending[tool_name]
    return pt


def _int_or_zero(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _process_event(
    event: StructuredEvent,
    trace: ExecutionTrace,
    pending: dict[str, list[_PendingTool]],
    pending_llm: list[_PendingLLMRequest],
) -> None:
    """Classify and process a single event."""
    et = event.event_type
    data = event.data

    if et == "session_start":
        trace.start_time = event.timestamp
        task_input = data.get("task_input") or data.get("query") or data.get("message")
        if isinstance(task_input, str):
            trace.task_input = task_input

    elif et == "session_end":
        trace.end_time = event.timestamp
        summary = data.get("summary")
        if isinstance(summary, dict):
            trace.total_tokens = int(summary.get("input_tokens", 0)) + int(
                summary.get("output_tokens", 0)
            )
        output = data.get("output") or data.get("result")
        if isinstance(output, str):
            trace.output = output

    elif et == "tool_start":
        tool_name = data.get("tool_name")
        if isinstance(tool_name, str):
            pending.setdefault(tool_name, []).append(
                _PendingTool(
                    sequence=event.sequence,
                    tool_name=tool_name,
                    start_time=event.timestamp,
                    input_data={
                        k: v
                        for k, v in data.items()
                        if not k.startswith("_") and k != "tool_name"
                    },
                )
            )

    elif et == "tool_end":
        tool_name = data.get("tool_name")
        if isinstance(tool_name, str):
            pt = _pop_pending(pending, tool_name)
            if pt:
                duration_ms = data.get("duration_ms")
                trace.tool_calls.append(
                    ToolCallRecord(
                        sequence=pt.sequence,
                        tool_name=pt.tool_name,
                        start_time=pt.start_time,
                        end_time=event.timestamp,
                        duration_ms=(
                            float(duration_ms)
                            if isinstance(duration_ms, (int, float))
                            else None
                        ),
                        success=True,
                        input_data=pt.input_data,
                        output_summary=_str_or_none(data.get("output_summary")),
                        output_data=data.get("output") or data.get("result"),
                    )
                )

    elif et == "tool_failure":
        tool_name = data.get("tool_name")
        if isinstance(tool_name, str):
            pt = _pop_pending(pending, tool_name)
            error_msg = data.get("error") or data.get("error_message") or ""
            duration_ms = data.get("duration_ms")
            trace.tool_calls.append(
                ToolCallRecord(
                    sequence=pt.sequence if pt else event.sequence,
                    tool_name=tool_name,
                    start_time=pt.start_time if pt else event.timestamp,
                    end_time=event.timestamp,
                    duration_ms=(
                        float(duration_ms)
                        if isinstance(duration_ms, (int, float))
                        else None
                    ),
                    success=False,
                    error=str(error_msg) if error_msg else None,
                    input_data=pt.input_data if pt else {},
                )
            )

    elif et == "error":
        trace.errors.append(
            {
                "timestamp": event.timestamp,
                "error": data.get("error") or data.get("message") or str(data),
                "error_type": data.get("error_type", "unknown"),
            }
        )

    elif et == "llm_request":
        pending_llm.append(
            _PendingLLMRequest(
                sequence=event.sequence,
                start_time=event.timestamp,
                model_name=_str_or_none(data.get("model_name")),
                prompt_preview=_str_or_none(data.get("prompt_preview")),
                message_count=_int_or_zero(data.get("message_count")),
            )
        )

    elif et == "token_usage":
        payload_data = data.get("data") if isinstance(data.get("data"), dict) else data
        usage = payload_data.get("usage", {})
        if isinstance(usage, dict):
            duration_ms_raw = payload_data.get("duration_ms")
            duration_ms = (
                float(duration_ms_raw)
                if isinstance(duration_ms_raw, (int, float))
                else None
            )
            pending_req = pending_llm.pop(0) if pending_llm else None
            end_time = event.timestamp
            if pending_req:
                start_time = pending_req.start_time
                sequence = pending_req.sequence
                model_name = pending_req.model_name or _str_or_none(payload_data.get("model_name"))
                prompt_preview = pending_req.prompt_preview
                message_count = pending_req.message_count
            else:
                sequence = event.sequence
                model_name = _str_or_none(payload_data.get("model_name"))
                prompt_preview = None
                message_count = 0
                if duration_ms is not None:
                    start_time = end_time - duration_ms / 1000.0
                else:
                    start_time = end_time

            trace.llm_calls.append(
                LLMCallRecord(
                    sequence=sequence,
                    start_time=start_time,
                    end_time=end_time,
                    model_name=model_name,
                    prompt_preview=prompt_preview,
                    message_count=message_count,
                    duration_ms=duration_ms,
                    ttft_ms=(
                        float(payload_data.get("ttft_ms"))
                        if payload_data.get("ttft_ms") is not None
                        else None
                    ),
                    prompt_tokens=int(usage.get("prompt_tokens", 0)),
                    completion_tokens=int(usage.get("completion_tokens", 0)),
                    total_tokens=int(usage.get("total_tokens", 0)),
                )
            )

    elif et == "tool_approval_request":
        trace.human_feedback.append(
            {
                "timestamp": event.timestamp,
                "tool_name": data.get("tool_name"),
                "action": data.get("action"),
                "approved": data.get("approved"),
            }
        )


def _str_or_none(value: object) -> str | None:
    """Safely extract a string or return None."""
    return str(value) if isinstance(value, str) else None
