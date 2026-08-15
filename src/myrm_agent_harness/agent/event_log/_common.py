"""Small helpers shared by trace aggregation modules.

Kept in their own module so the aggregation modules (trace_builder and its
``_pairing``/``_llm``/``_tasks_steps`` helpers) can share them without
circular imports.
"""

from __future__ import annotations

# Keys on tool_start / tasks_steps payloads that carry step/bookkeeping
# metadata rather than tool input — stripped before storing input_data.
# Shared so both aggregation paths filter identically.
_EVENT_META_KEYS: frozenset[str] = frozenset(
    {
        "_agent_id",
        "_user_id",
        "_task_type",
        "_trace_id",
        "cancel_reason",
        "count",
        "data",  # display rows (text), not tool input
        "duration_ms",
        "end_time",
        "error",
        "error_category",
        "error_hint",
        "evicted_ref",
        "fault_side",
        "messageId",
        "message_id",
        "reason",
        "result",
        "session_id",
        "start_time",
        "status",
        "step_key",
        "tool_call_id",
        "tool_name",
        "version",
    }
)


def _str_or_none(value: object) -> str | None:
    """Safely extract a string or return None."""
    return str(value) if isinstance(value, str) else None


def _int_or_zero(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0
