"""Trace builder — constructs ExecutionTrace from raw event streams.

Reads events from EventLogBackend and aggregates them into a structured
ExecutionTrace for task-level replay, scoring, and pattern extraction.

The aggregation is split across focused helper modules to keep each one small
and single-purpose:

- ``_pairing`` — tool-call pairing state machine (tool_start → tool_end)
- ``_llm`` — llm_request → token_usage aggregation into LLMCallRecord
- ``_tasks_steps`` — merging streaming ``tasks_steps`` progress events
- ``_common`` — shared string/number coercion helpers

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

from ._common import _str_or_none
from ._llm import _handle_llm_request, _handle_token_usage, _PendingLLMRequest
from ._pairing import (
    _find_tool_record,
    _PendingTool,
    _pop_pending,
    _replace_tool_record,
)
from ._tasks_steps import _process_tasks_step
from .trace_types import ExecutionTrace, ToolCallRecord, TraceMetadata, TraceOutcome
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
    event_filter = EventFilter(start_sequence=start_sequence) if start_sequence else None
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
        first_idx, first_ts = _find_first_irrecoverable(trace.errors, trace.tool_calls)
        trace.first_irrecoverable_index = first_idx
        trace.first_irrecoverable_timestamp = first_ts
    elif trace.end_time > 0:
        trace.outcome = TraceOutcome.SUCCESS

    return trace


def _extract_metadata(event: StructuredEvent) -> TraceMetadata:
    """Extract context dimensions from the first event's data."""
    data = event.data
    return TraceMetadata(
        user_id=_str_or_none(data.get("_user_id")),
        agent_id=_str_or_none(data.get("_agent_id")),
        task_type=_str_or_none(data.get("_task_type")),
        trace_id=_str_or_none(data.get("_trace_id")),
    )


def _find_first_irrecoverable(
    errors: list[dict[str, object]], tool_calls: list[ToolCallRecord]
) -> tuple[int | None, float | None]:
    """Locate the earliest failure from which execution never recovered.

    The "irrecoverable chain" starts at the first error whose timestamp is
    later than the last successful tool call: anything after that point ran
    without a successful recovery (failover/replan may have rescued earlier
    errors).  When there is no successful tool call at all, the first error is
    the root cause.

    Returns ``(errors_index, timestamp)`` for the first unrecovered error, or
    ``(None, None)`` when every error was succeeded by a successful tool call
    (execution recovered) or when no errors exist.
    """
    if not errors:
        return None, None

    last_success_end = max(
        (tc.end_time for tc in tool_calls if tc.success and tc.end_time is not None),
        default=None,
    )
    if last_success_end is None:
        return 0, float(errors[0].get("timestamp", 0) or 0)

    for idx, err in enumerate(errors):
        ts = err.get("timestamp")
        if isinstance(ts, (int, float)) and ts > last_success_end:
            return idx, float(ts)
    # Every error predates the last successful tool call — each was recovered.
    return None, None


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
            trace.total_tokens = int(summary.get("input_tokens", 0)) + int(summary.get("output_tokens", 0))
        output = data.get("output") or data.get("result")
        if isinstance(output, str):
            trace.output = output

    elif et == "tool_start":
        tool_name = data.get("tool_name")
        if isinstance(tool_name, str):
            tool_call_id = _str_or_none(data.get("tool_call_id"))
            # The same invocation may already be recorded from a tasks_steps
            # progress event; keep it as one record instead of duplicating.
            if _find_tool_record(trace.tool_calls, tool_call_id) is None:
                pending.setdefault(tool_name, []).append(
                    _PendingTool(
                        sequence=event.sequence,
                        tool_name=tool_name,
                        start_time=event.timestamp,
                        input_data={k: v for k, v in data.items() if not k.startswith("_") and k != "tool_name"},
                        tool_call_id=tool_call_id,
                        message_id=_str_or_none(data.get("message_id")),
                    )
                )

    elif et == "tool_end":
        tool_name = data.get("tool_name")
        if isinstance(tool_name, str):
            tool_call_id = _str_or_none(data.get("tool_call_id"))
            pt = _pop_pending(pending, tool_name, tool_call_id)
            existing = _find_tool_record(trace.tool_calls, tool_call_id)
            duration_ms = data.get("duration_ms")
            duration = float(duration_ms) if isinstance(duration_ms, (int, float)) else None
            if existing is not None:
                # The same invocation may already be recorded from a tasks_steps
                # progress event even when no pending tool_start was seen.
                _replace_tool_record(
                    trace,
                    existing,
                    end_time=event.timestamp,
                    duration_ms=duration,
                    success=True,
                    output_summary=_str_or_none(data.get("output_summary")),
                    output_data=data.get("output") or data.get("result"),
                )
            elif pt is not None:
                trace.tool_calls.append(
                    ToolCallRecord(
                        sequence=pt.sequence,
                        tool_name=pt.tool_name,
                        start_time=pt.start_time,
                        end_time=event.timestamp,
                        duration_ms=duration,
                        success=True,
                        tool_call_id=pt.tool_call_id,
                        message_id=pt.message_id,
                        input_data=pt.input_data,
                        output_summary=_str_or_none(data.get("output_summary")),
                        output_data=data.get("output") or data.get("result"),
                    )
                )

    elif et == "tool_failure":
        tool_name = data.get("tool_name")
        if isinstance(tool_name, str):
            tool_call_id = _str_or_none(data.get("tool_call_id"))
            pt = _pop_pending(pending, tool_name, tool_call_id)
            error_msg = data.get("error") or data.get("error_message") or ""
            duration_ms = data.get("duration_ms")
            duration = float(duration_ms) if isinstance(duration_ms, (int, float)) else None
            existing = _find_tool_record(trace.tool_calls, tool_call_id)
            if existing is not None:
                _replace_tool_record(
                    trace,
                    existing,
                    end_time=event.timestamp,
                    duration_ms=duration,
                    success=False,
                    error=str(error_msg) if error_msg else None,
                    fault_side=_str_or_none(data.get("fault_side")) or existing.fault_side,
                )
            elif pt is not None:
                trace.tool_calls.append(
                    ToolCallRecord(
                        sequence=pt.sequence,
                        tool_name=tool_name,
                        start_time=pt.start_time,
                        end_time=event.timestamp,
                        duration_ms=duration,
                        success=False,
                        error=str(error_msg) if error_msg else None,
                        tool_call_id=pt.tool_call_id,
                        message_id=pt.message_id,
                        input_data=pt.input_data,
                        fault_side=_str_or_none(data.get("fault_side")),
                    )
                )
            else:
                trace.tool_calls.append(
                    ToolCallRecord(
                        sequence=event.sequence,
                        tool_name=tool_name,
                        start_time=event.timestamp,
                        end_time=event.timestamp,
                        duration_ms=(float(duration_ms) if isinstance(duration_ms, (int, float)) else None),
                        success=False,
                        error=str(error_msg) if error_msg else None,
                        tool_call_id=tool_call_id,
                        message_id=_str_or_none(data.get("message_id")),
                        input_data={},
                        fault_side=_str_or_none(data.get("fault_side")),
                    )
                )

    elif et == "tasks_steps":
        _process_tasks_step(event, trace)

    elif et == "error":
        error_entry: dict[str, object] = {
            "timestamp": event.timestamp,
            "error": data.get("error") or data.get("message") or str(data),
            "error_type": data.get("error_type", "unknown"),
        }
        # Deterministic attribution + recovery guidance for the GUI's post-mortem
        # view: fault side (who owns the failure), error kind, recovery actions,
        # and the localized diagnostic payload.
        if fault_side := _str_or_none(data.get("fault_side")):
            error_entry["fault_side"] = fault_side
        if error_kind := _str_or_none(data.get("error_kind")):
            error_entry["error_kind"] = error_kind
        recovery_actions = data.get("recovery_actions")
        if isinstance(recovery_actions, list):
            error_entry["recovery_actions"] = recovery_actions
        diagnostic = data.get("diagnostic_result")
        if isinstance(diagnostic, dict):
            error_entry["diagnostic_result"] = diagnostic
        trace.errors.append(error_entry)

    elif et == "llm_request":
        _handle_llm_request(event, pending_llm)

    elif et == "token_usage":
        _handle_token_usage(event, trace, pending_llm)

    elif et == "tool_approval_request":
        trace.human_feedback.append(
            {
                "timestamp": event.timestamp,
                "tool_name": data.get("tool_name"),
                "action": data.get("action"),
                "approved": data.get("approved"),
            }
        )
