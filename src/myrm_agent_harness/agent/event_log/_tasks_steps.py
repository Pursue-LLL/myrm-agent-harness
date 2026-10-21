"""Merging of streaming ``tasks_steps`` progress events into the trace.

The streaming layer (``streaming.event_handlers``) emits tool invocations as
``tasks_steps`` events in addition to — or instead of — the ``tool_start``/
``tool_end`` lifecycle pair.  This module turns those steps into lineaged
``ToolCallRecord`` entries and closes/annotates them on terminal or error steps.

[POS]
Internal read-side helper of trace_builder.  Not part of the public API.
"""

from __future__ import annotations

from ._common import _EVENT_META_KEYS, _str_or_none
from ._pairing import _find_open_record_by_context, _find_tool_record, _replace_tool_record
from .trace_types import ExecutionTrace, ToolCallRecord
from .types import StructuredEvent

# A tasks_steps step may carry a terminal status; any other status (including an
# absent one) is treated as "still running" and recorded with no end time.
_TERMINAL_TOOL_STATUSES: frozenset[str] = frozenset(
    {"cancelled", "completed", "done", "error", "failed", "succeeded", "success"}
)
_FAILURE_TOOL_STATUSES: frozenset[str] = frozenset({"cancelled", "error", "failed"})


def _process_tasks_step(event: StructuredEvent, trace: ExecutionTrace) -> None:
    """Merge a ``tasks_steps`` progress event into the trace.

    A step that names a tool therefore represents one tool invocation: record it
    immediately, then let a later terminal ``tool_end``/``tool_failure`` or
    error-status step refine it.
    """
    data = event.data
    tool_name = data.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name:
        return  # plan steps / source reviews carry no tool_name

    tool_call_id = _str_or_none(data.get("tool_call_id"))
    message_id = _str_or_none(data.get("message_id")) or _str_or_none(data.get("messageId"))
    status = _str_or_none(data.get("status"))
    step_key = _str_or_none(data.get("step_key")) or ""

    is_failure = status in _FAILURE_TOOL_STATUSES or step_key.endswith("_error")
    is_terminal = status in _TERMINAL_TOOL_STATUSES or is_failure

    existing = _find_tool_record(trace.tool_calls, tool_call_id)
    if existing is None and is_failure:
        existing = _find_open_record_by_context(trace.tool_calls, tool_name, message_id)
    if existing is not None:
        if is_failure:
            _replace_tool_record(
                trace,
                existing,
                end_time=event.timestamp,
                success=False,
                error=_str_or_none(data.get("error")) or existing.error,
                fault_side=_str_or_none(data.get("fault_side")) or existing.fault_side,
            )
        elif is_terminal:
            _replace_tool_record(trace, existing, end_time=event.timestamp)
        return

    input_data = {k: v for k, v in data.items() if k not in _EVENT_META_KEYS}

    if is_failure:
        trace.tool_calls.append(
            ToolCallRecord(
                sequence=event.sequence,
                tool_name=tool_name,
                start_time=event.timestamp,
                end_time=event.timestamp,
                success=False,
                error=_str_or_none(data.get("error")),
                tool_call_id=tool_call_id,
                message_id=message_id,
                input_data=input_data,
                fault_side=_str_or_none(data.get("fault_side")),
            )
        )
        return

    trace.tool_calls.append(
        ToolCallRecord(
            sequence=event.sequence,
            tool_name=tool_name,
            start_time=event.timestamp,
            success=not is_failure,  # running/succeeded steps are successes until closed
            tool_call_id=tool_call_id,
            message_id=message_id,
            input_data=input_data,
        )
    )
