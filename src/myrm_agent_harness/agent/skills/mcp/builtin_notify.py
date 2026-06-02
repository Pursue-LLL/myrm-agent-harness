"""PTC builtin: ``tools.notify`` — push real-time status from PTC to the UI.

Long-running PTC scripts often want to surface intermediate progress (e.g.
"finished crawling 80/200 URLs", "found an anomaly at index 47") without
ending the script. ``tools.notify`` wraps :func:`dispatch_custom_event` so
PTC code can fire ``ptc_notify`` events that flow through LangGraph's
custom stream all the way to the frontend inline activity card.

Cross-task delivery is achieved via :mod:`notify_registry`: the bash tool
publishes its RunnableConfig under the session_id before invoking the
executor, and this handler retrieves the same config (looked up via the IPC
call context) so the event reaches the correct UI session.

A per-session token-bucket rate limit (10 req/s burst 20) protects the UI
from a runaway ``for i in range(N): notify(...)`` script — overflowing
calls are dropped silently with a debug log; the script continues running.

Structured progress fields (``progress`` 0-100, ``step_index``,
``total_steps``, ``category``) let the frontend render a real progress bar
instead of stacking textual toasts; they are optional so simple
``notify("hello")`` calls stay ergonomic.

[INPUT]
- agent.skills.mcp.ipc_proxy::get_ipc_call_context (POS: IPC call context.)
- agent.skills.mcp.notify_registry::get_session_config (POS: Session→config lookup.)
- utils.event_utils::dispatch_custom_event (POS: LangGraph custom stream writer.)

[OUTPUT]
- notify_handler: BuiltinHandler dispatching to the LangGraph stream.

[POS]
Cross-process realtime progress channel for PTC scripts.
"""

from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Final

logger = logging.getLogger(__name__)

_ALLOWED_LEVELS: Final[frozenset[str]] = frozenset({"info", "warn", "alert"})
_MAX_MESSAGE_BYTES: Final[int] = 4 * 1024
_MAX_CATEGORY_LEN: Final[int] = 32

# Token bucket: each session refills at ``_RATE_PER_SEC`` tokens/second and
# caps at ``_BURST`` tokens. Cheap enough for tens of thousands of sessions
# in process memory (a few floats per session).
_RATE_PER_SEC: Final[float] = 10.0
_BURST: Final[float] = 20.0

_bucket_state: dict[str, tuple[float, float]] = {}
_bucket_lock = Lock()


class NotifyError(Exception):
    """Raised when a notify payload is malformed."""


def _consume_token(session_id: str) -> bool:
    """Best-effort token-bucket admission; returns True when the call is allowed.

    Falls back to True (always allow) for callers without a session_id so
    standalone tests / one-off scripts are unaffected.
    """
    if not session_id:
        return True
    now = time.monotonic()
    with _bucket_lock:
        tokens, last = _bucket_state.get(session_id, (_BURST, now))
        tokens = min(_BURST, tokens + (now - last) * _RATE_PER_SEC)
        if tokens < 1.0:
            _bucket_state[session_id] = (tokens, now)
            return False
        _bucket_state[session_id] = (tokens - 1.0, now)
        return True


def _coerce_optional_int(value: object, *, lo: int, hi: int, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise NotifyError(f"notify: '{field}' must be an int in [{lo}, {hi}].")
    if value < lo or value > hi:
        raise NotifyError(f"notify: '{field}' must be in [{lo}, {hi}] (got {value}).")
    return value


async def notify_handler(params: dict[str, object]) -> None:
    """Forward a PTC notification to the LangGraph custom event stream.

    Args:
        params: dict with the following keys:
            - ``message`` (str, required): Human-readable status line.
            - ``level`` (str, optional, default ``"info"``): One of
              ``info`` / ``warn`` / ``alert``.
            - ``progress`` (int, optional, 0..100): Completion percentage.
            - ``step_index`` (int, optional, ≥1): Current step within a sequence.
            - ``total_steps`` (int, optional, ≥1): Total step count.
            - ``category`` (str, optional, ≤32 chars): Free-form bucket so the
              frontend can group repeated notifications (``crawl`` / ``parse``).

    Returns:
        ``None``. Notifications are fire-and-forget: when no LangGraph
        consumer is registered for the session, or the per-session
        rate-limit bucket is empty, the event is dropped silently to
        preserve "best-effort progress" semantics without crashing the
        PTC script.
    """
    message = params.get("message")
    if not isinstance(message, str) or not message:
        raise NotifyError("notify: 'message' must be a non-empty string.")
    if len(message.encode("utf-8")) > _MAX_MESSAGE_BYTES:
        raise NotifyError(
            f"notify: message exceeds {_MAX_MESSAGE_BYTES // 1024} KiB; "
            "summarise before sending."
        )

    level_raw = params.get("level", "info")
    level = level_raw if isinstance(level_raw, str) else "info"
    if level not in _ALLOWED_LEVELS:
        raise NotifyError(
            f"notify: invalid level '{level}'. Expected one of {sorted(_ALLOWED_LEVELS)}."
        )

    progress = _coerce_optional_int(params.get("progress"), lo=0, hi=100, field="progress")
    step_index = _coerce_optional_int(
        params.get("step_index"), lo=1, hi=10_000_000, field="step_index"
    )
    total_steps = _coerce_optional_int(
        params.get("total_steps"), lo=1, hi=10_000_000, field="total_steps"
    )

    category_raw = params.get("category")
    category: str | None
    if category_raw is None:
        category = None
    elif isinstance(category_raw, str) and category_raw:
        if len(category_raw) > _MAX_CATEGORY_LEN:
            raise NotifyError(
                f"notify: 'category' must be ≤ {_MAX_CATEGORY_LEN} chars (got {len(category_raw)})."
            )
        category = category_raw
    else:
        raise NotifyError("notify: 'category' must be a non-empty string when provided.")

    from myrm_agent_harness.agent.skills.mcp.ipc_proxy import get_ipc_call_context
    from myrm_agent_harness.agent.skills.mcp.notify_registry import get_session_config
    from myrm_agent_harness.utils.event_utils import dispatch_custom_event

    ctx = get_ipc_call_context()
    session_id = ctx.session_id if ctx else None
    config = get_session_config(session_id) if session_id else None

    if session_id and not _consume_token(session_id):
        logger.debug(
            "notify_handler: rate limited session=%s (>10 req/s burst 20)", session_id
        )
        return None

    payload: dict[str, object] = {
        "event": "ptc_notify",
        "level": level,
        "message": message,
        "session_id": session_id,
        "trace_id": ctx.trace_id if ctx else None,
    }
    if progress is not None:
        payload["progress"] = progress
    if step_index is not None:
        payload["step_index"] = step_index
    if total_steps is not None:
        payload["total_steps"] = total_steps
    if category is not None:
        payload["category"] = category

    try:
        await dispatch_custom_event("ptc_notify", payload, config=config)
    except Exception as exc:
        logger.warning("notify_handler: dispatch_custom_event failed: %s", exc)

    return None


__all__ = ["NotifyError", "notify_handler"]
