"""Observability type definitions — zero-dependency pure types.

[INPUT]
None (zero-dependency)

[OUTPUT]
- ToolCallEventData: Immutable tool call event data
- EventCallback: Type alias for event subscribers

[POS]
Pure data structure definitions for observability subsystem.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from myrm_agent_harness.utils.text_utils import smart_truncate


def _truncate_for_event(obj: object, max_bytes: int = 1024) -> object:
    """Truncate tool result for event broadcasting.

    Strategy:
    - None/bool/int/float → return as-is
    - str → smart_truncate (tail_ratio=0.3 for intelligent error detection)
    - dict/list → json.dumps() → smart_truncate
    - other → repr() → smart_truncate

    Args:
        obj: Tool result or error object to truncate.
        max_bytes: Maximum bytes for truncated output (default 1KB).

    Returns:
        Truncated object suitable for EventBus.
    """
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj

    if isinstance(obj, str):
        return smart_truncate(obj, max_bytes, tail_ratio=0.3) if len(obj) > max_bytes else obj

    try:
        serialized = json.dumps(obj, ensure_ascii=False, indent=None)
        return smart_truncate(serialized, max_bytes, tail_ratio=0.3) if len(serialized) > max_bytes else serialized
    except (TypeError, ValueError):
        repr_str = repr(obj)
        return smart_truncate(repr_str, max_bytes, tail_ratio=0.3) if len(repr_str) > max_bytes else repr_str


@dataclass(frozen=True, slots=True)
class ToolCallEventData:
    """Immutable tool call event data for EventBus broadcasting."""

    tool_name: str
    status: Literal["started", "completed", "failed", "cancelled"]
    start_time: float
    end_time: float | None = None
    duration_ms: int | None = None
    args: dict[str, object] | None = None
    result: object | None = None
    error: str | None = None
    session_id: str | None = None
    message_id: str | None = None
    tool_call_id: str | None = None
    cancel_reason: str | None = None  # "user_cancelled" | "timeout" | "session_ended"
    version: int | None = None
    evicted_ref: str | None = None  # Evicted output filename (for GUI viewer)

    def to_dict(self) -> dict[str, object]:
        """Export to dict for business layer serialization."""
        result: dict[str, object] = {
            "tool_name": self.tool_name,
            "status": self.status,
            "start_time": round(self.start_time, 3),
        }
        if self.end_time is not None:
            result["end_time"] = round(self.end_time, 3)
        if self.duration_ms is not None:
            result["duration_ms"] = self.duration_ms
        if self.args is not None:
            result["args"] = self.args
        if self.result is not None:
            result["result"] = self.result
        if self.error is not None:
            result["error"] = self.error
        if self.session_id is not None:
            result["session_id"] = self.session_id
        if self.message_id is not None:
            result["message_id"] = self.message_id
        if self.tool_call_id is not None:
            result["tool_call_id"] = self.tool_call_id
        if self.cancel_reason is not None:
            result["cancel_reason"] = self.cancel_reason
        if self.version is not None:
            result["version"] = self.version
        if self.evicted_ref is not None:
            result["evicted_ref"] = self.evicted_ref
        return result

    def to_json(self) -> str:
        """Export to JSON string for SSE/WebSocket transport."""
        return json.dumps(self.to_dict(), ensure_ascii=False)


EventCallback = Callable[[ToolCallEventData], Awaitable[None]]
