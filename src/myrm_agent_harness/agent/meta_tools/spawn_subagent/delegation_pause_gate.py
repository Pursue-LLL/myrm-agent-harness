"""Session-scoped delegation pause gate.

Blocks new subagent spawns while allowing in-flight children to finish.
Used by REST control plane and delegate_task_tool entry points.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_paused_sessions: set[str] = set()


def _normalize_session_id(session_id: str | None) -> str:
    return (session_id or "").strip()


def _session_aliases(session_id: str | None) -> set[str]:
    """Return REST chat_id and harness session_id aliases for the same conversation."""
    sid = _normalize_session_id(session_id)
    if not sid:
        return set()
    aliases = {sid}
    if sid.startswith("chat_"):
        aliases.add(sid.removeprefix("chat_"))
    else:
        aliases.add(f"chat_{sid}")
    return aliases


def is_delegation_paused(session_id: str | None) -> bool:
    aliases = _session_aliases(session_id)
    if not aliases:
        return False
    with _lock:
        return bool(aliases & _paused_sessions)


def pause_delegation(session_id: str) -> bool:
    aliases = _session_aliases(session_id)
    if not aliases:
        return False
    with _lock:
        _paused_sessions.update(aliases)
    return True


def resume_delegation(session_id: str) -> bool:
    aliases = _session_aliases(session_id)
    if not aliases:
        return False
    with _lock:
        _paused_sessions.difference_update(aliases)
    return True


def delegation_pause_status(session_id: str) -> dict[str, object]:
    sid = _normalize_session_id(session_id)
    paused = is_delegation_paused(sid)
    return {"session_id": sid, "paused": paused}
