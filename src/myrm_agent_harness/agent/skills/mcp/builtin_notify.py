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
- agent.skills.mcp.progress_payload::parse_ptc_notify_params, build_ptc_notify_payload
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

from myrm_agent_harness.agent.skills.mcp.progress_payload import (
    NotifyError,
    build_ptc_notify_payload,
    parse_ptc_notify_params,
)

logger = logging.getLogger(__name__)

# Token bucket: each session refills at ``_RATE_PER_SEC`` tokens/second and
# caps at ``_BURST`` tokens. Cheap enough for tens of thousands of sessions
# in process memory (a few floats per session).
_RATE_PER_SEC: Final[float] = 10.0
_BURST: Final[float] = 20.0

_bucket_state: dict[str, tuple[float, float]] = {}
_bucket_lock = Lock()


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
    fields = parse_ptc_notify_params(params)

    from myrm_agent_harness.agent.skills.mcp.ipc_proxy import get_ipc_call_context
    from myrm_agent_harness.agent.skills.mcp.notify_registry import get_session_config
    from myrm_agent_harness.utils.event_utils import dispatch_custom_event

    ctx = get_ipc_call_context()
    session_id = ctx.session_id if ctx else None
    config = get_session_config(session_id) if session_id else None

    if session_id and not _consume_token(session_id):
        logger.debug("notify_handler: rate limited session=%s (>10 req/s burst 20)", session_id)
        return None

    payload = build_ptc_notify_payload(
        fields,
        session_id=session_id,
        trace_id=ctx.trace_id if ctx else None,
    )

    try:
        await dispatch_custom_event("ptc_notify", payload, config=config)
    except Exception as exc:
        logger.warning("notify_handler: dispatch_custom_event failed: %s", exc)

    return None


__all__ = ["NotifyError", "notify_handler"]
