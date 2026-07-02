"""Shared notify/progress field normalization for PTC and DW paths.

PTC ``notify_handler`` validates strictly (raises on bad input).
DW ``NotifyProgressTool`` normalizes leniently (clamp/truncate) for script ergonomics.
Both paths share level/category/message bounds so ASCS stays consistent.

[INPUT]
- (none — pure validation/build helpers)

[OUTPUT]
- parse_ptc_notify_params / build_ptc_notify_payload: PTC ``ptc_notify`` stream
- build_workflow_stage_event: DW ``workflow_stage`` SSE events

[POS]
Single source of truth for notify field bounds shared across PTC and DW paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

ALLOWED_LEVELS: Final[frozenset[str]] = frozenset({"info", "warn", "alert"})
MAX_MESSAGE_BYTES: Final[int] = 4 * 1024
MAX_DW_DISPLAY_MESSAGE: Final[int] = 500
MAX_CATEGORY_LEN: Final[int] = 32
MAX_STEP_BOUND: Final[int] = 10_000_000
DW_INDETERMINATE_PROGRESS: Final[int] = -1


class NotifyError(Exception):
    """Raised when a notify payload is malformed."""


@dataclass(frozen=True, slots=True)
class NormalizedProgressFields:
    message: str
    level: str
    progress: int | None
    step_index: int | None
    total_steps: int | None
    category: str | None


def normalize_level(raw: object, *, strict: bool) -> str:
    level = raw if isinstance(raw, str) else "info"
    if level in ALLOWED_LEVELS:
        return level
    if strict:
        raise NotifyError(f"notify: invalid level '{level}'. Expected one of {sorted(ALLOWED_LEVELS)}.")
    return "info"


def _coerce_optional_bounded_int(value: object, *, lo: int, hi: int, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise NotifyError(f"notify: '{field}' must be an int in [{lo}, {hi}].")
    if value < lo or value > hi:
        raise NotifyError(f"notify: '{field}' must be in [{lo}, {hi}] (got {value}).")
    return value


def _validate_message(message: object) -> str:
    if not isinstance(message, str) or not message:
        raise NotifyError("notify: 'message' must be a non-empty string.")
    if len(message.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise NotifyError(f"notify: message exceeds {MAX_MESSAGE_BYTES // 1024} KiB; summarise before sending.")
    return message


def parse_ptc_notify_params(params: dict[str, object]) -> NormalizedProgressFields:
    message = _validate_message(params.get("message"))
    level = normalize_level(params.get("level", "info"), strict=True)
    progress = _coerce_optional_bounded_int(params.get("progress"), lo=0, hi=100, field="progress")
    step_index = _coerce_optional_bounded_int(
        params.get("step_index"), lo=1, hi=MAX_STEP_BOUND, field="step_index"
    )
    total_steps = _coerce_optional_bounded_int(
        params.get("total_steps"), lo=1, hi=MAX_STEP_BOUND, field="total_steps"
    )

    category_raw = params.get("category")
    category: str | None
    if category_raw is None:
        category = None
    elif isinstance(category_raw, str) and category_raw:
        if len(category_raw) > MAX_CATEGORY_LEN:
            raise NotifyError(f"notify: 'category' must be ≤ {MAX_CATEGORY_LEN} chars (got {len(category_raw)}).")
        category = category_raw
    else:
        raise NotifyError("notify: 'category' must be a non-empty string when provided.")

    return NormalizedProgressFields(
        message=message,
        level=level,
        progress=progress,
        step_index=step_index,
        total_steps=total_steps,
        category=category,
    )


def normalize_dw_progress(progress: int) -> int:
    return max(DW_INDETERMINATE_PROGRESS, min(100, progress))


def normalize_dw_step_index(step_index: int) -> int:
    return max(0, step_index)


def normalize_dw_category(category: str) -> str:
    return category[:MAX_CATEGORY_LEN]


def normalize_dw_message(message: str) -> str:
    return message[:MAX_DW_DISPLAY_MESSAGE]


def build_ptc_notify_payload(
    fields: NormalizedProgressFields,
    *,
    session_id: str | None,
    trace_id: str | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "event": "ptc_notify",
        "level": fields.level,
        "message": fields.message,
        "session_id": session_id,
        "trace_id": trace_id,
    }
    if fields.progress is not None:
        payload["progress"] = fields.progress
    if fields.step_index is not None:
        payload["step_index"] = fields.step_index
    if fields.total_steps is not None:
        payload["total_steps"] = fields.total_steps
    if fields.category is not None:
        payload["category"] = fields.category
    return payload


def build_workflow_stage_event(
    message_id: str,
    message: str,
    *,
    progress: int = DW_INDETERMINATE_PROGRESS,
    step_index: int = 0,
    total_steps: int = 0,
    category: str = "",
    level: str = "info",
) -> dict[str, object]:
    validated_level = normalize_level(level, strict=False)
    return {
        "type": "status",
        "step_key": "workflow_stage",
        "messageId": message_id,
        "status": "in_progress",
        "data": {
            "message": normalize_dw_message(message),
            "notify_progress": normalize_dw_progress(progress),
            "notify_step_index": normalize_dw_step_index(step_index),
            "notify_total_steps": normalize_dw_step_index(total_steps),
            "notify_category": normalize_dw_category(category),
            "notify_level": validated_level,
        },
    }


__all__ = [
    "ALLOWED_LEVELS",
    "DW_INDETERMINATE_PROGRESS",
    "MAX_CATEGORY_LEN",
    "MAX_DW_DISPLAY_MESSAGE",
    "MAX_MESSAGE_BYTES",
    "NotifyError",
    "NormalizedProgressFields",
    "build_ptc_notify_payload",
    "build_workflow_stage_event",
    "normalize_dw_category",
    "normalize_dw_message",
    "normalize_dw_progress",
    "normalize_dw_step_index",
    "normalize_level",
    "parse_ptc_notify_params",
]
