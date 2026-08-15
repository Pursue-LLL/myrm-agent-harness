"""Tool-call pairing state machine for trace aggregation.

Tracks ``tool_start`` events awaiting their terminal ``tool_end``/``tool_failure``
and resolves records by ``tool_call_id`` (falling back to FIFO-by-name for
id-less legacy streams) so concurrent invocations of the same tool never
cross-pair.

[POS]
Internal read-side helper of trace_builder.  Not part of the public API.
"""

from __future__ import annotations

from dataclasses import replace

from .trace_types import ExecutionTrace, ToolCallRecord


class _PendingTool:
    """Tracks a tool_start waiting for its tool_end/tool_failure."""

    __slots__ = (
        "input_data",
        "message_id",
        "sequence",
        "start_time",
        "tool_call_id",
        "tool_name",
    )

    def __init__(
        self,
        sequence: int,
        tool_name: str,
        start_time: float,
        input_data: dict[str, object],
        tool_call_id: str | None = None,
        message_id: str | None = None,
    ) -> None:
        self.sequence = sequence
        self.tool_name = tool_name
        self.start_time = start_time
        self.input_data = input_data
        self.tool_call_id = tool_call_id
        self.message_id = message_id


def _pop_pending(
    pending: dict[str, list[_PendingTool]], tool_name: str, tool_call_id: str | None = None
) -> _PendingTool | None:
    """Pop the matching pending tool.

    Prefers an exact ``tool_call_id`` match (concurrent/re-entrant invocations
    of the same tool must not be paired by name alone); falls back to the
    oldest entry for ``tool_name`` (FIFO) when the id is absent — e.g. legacy
    or id-less event streams.
    """
    queue = pending.get(tool_name)
    if not queue:
        return None

    if tool_call_id:
        for idx, pt in enumerate(queue):
            if pt.tool_call_id == tool_call_id:
                queue.pop(idx)
                if not queue:
                    del pending[tool_name]
                return pt

    pt = queue.pop(0)
    if not queue:
        del pending[tool_name]
    return pt


def _find_tool_record(
    tool_calls: list[ToolCallRecord], tool_call_id: str | None
) -> ToolCallRecord | None:
    """Find an already-recorded tool call by its ``tool_call_id``.

    The same invocation can surface both as a ``tasks_steps`` progress event and
    as ``tool_start``/``tool_end`` pair — the id keeps them as one record.
    """
    if not tool_call_id:
        return None
    for tc in tool_calls:
        if tc.tool_call_id == tool_call_id:
            return tc
    return None


def _replace_tool_record(
    trace: ExecutionTrace,
    existing: ToolCallRecord,
    **changes: object,
) -> None:
    """Swap ``existing`` with a copy carrying ``changes`` (frozen record)."""
    trace.tool_calls = [
        replace(existing, **changes) if tc is existing else tc for tc in trace.tool_calls
    ]


def _find_open_record_by_context(
    tool_calls: list[ToolCallRecord], tool_name: str, message_id: str | None
) -> ToolCallRecord | None:
    """Find the most recent open (unclosed) record for a tool+message context.

    Error-status ``tasks_steps`` steps (see streaming.event_handlers) carry
    tool_name + messageId but no tool_call_id; closing the matching running
    record keeps the lineage intact instead of creating a duplicate.
    """
    if not message_id:
        return None
    for tc in reversed(tool_calls):
        if tc.tool_name == tool_name and tc.message_id == message_id and tc.end_time is None:
            return tc
    return None
