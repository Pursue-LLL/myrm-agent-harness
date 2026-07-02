"""Merge active subagent rows for a chat session from gateway and ACTIVE_SUBAGENTS.

[INPUT]
- manager::ACTIVE_SUBAGENTS, ACTIVE_SUBAGENT_SESSIONS, SubagentManager (POS: global registry for server control without gateway session)
- _manager_control::SubagentControlMixin.list_children (POS: active child rows)

[OUTPUT]
- merge_active_subagent_children: deduped active rows for one session_id
- cancel_active_children_for_session: cancel all running children for one session_id via registry

[POS]
Server REST/SSE subagent tree uses the same registry as cancel_subagent when the parent agent session is gone.
"""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.manager import (
    ACTIVE_SUBAGENT_SESSIONS,
    ACTIVE_SUBAGENTS,
    SubagentManager,
)


def _session_id_candidates(session_id: str) -> set[str]:
    normalized = session_id.strip()
    if not normalized:
        return set()
    candidates = {normalized}
    if normalized.startswith("chat_"):
        candidates.add(normalized.removeprefix("chat_"))
    else:
        candidates.add(f"chat_{normalized}")
    return candidates


def _manager_session_id(manager: SubagentManager) -> str:
    parent = manager._parent_agent
    direct = getattr(parent, "session_id", None)
    if direct is not None:
        normalized = str(direct).strip()
        if normalized:
            return normalized

    last_context = getattr(parent, "_last_context", None)
    if isinstance(last_context, dict):
        ctx_session_id = last_context.get("session_id")
        if isinstance(ctx_session_id, str) and ctx_session_id.strip():
            return ctx_session_id.strip()

    return ""


def _task_session_id(task_id: str, manager: SubagentManager) -> str:
    mapped = ACTIVE_SUBAGENT_SESSIONS.get(task_id, "").strip()
    if mapped:
        return mapped
    return _manager_session_id(manager)


def list_active_children_from_registry(session_id: str) -> list[dict[str, object]]:
    """Return running/recent child rows for session_id via ACTIVE_SUBAGENTS (no gateway required)."""
    candidates = _session_id_candidates(session_id)
    if not candidates:
        return []

    seen_managers: set[int] = set()
    merged: dict[str, dict[str, object]] = {}

    for task_id, manager in ACTIVE_SUBAGENTS.items():
        manager_key = id(manager)
        if manager_key in seen_managers:
            continue
        if _task_session_id(task_id, manager) not in candidates:
            continue
        seen_managers.add(manager_key)
        for child in manager.list_children():
            if not isinstance(child, dict):
                continue
            child_task_id = child.get("task_id")
            if isinstance(child_task_id, str) and child_task_id:
                merged[child_task_id] = child

    return list(merged.values())


def merge_active_subagent_children(
    session_id: str,
    gateway_children: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Merge gateway list_children rows with ACTIVE_SUBAGENTS rows for the same session."""
    merged: dict[str, dict[str, object]] = {}

    for row in gateway_children or []:
        if not isinstance(row, dict):
            continue
        task_id = row.get("task_id")
        if isinstance(task_id, str) and task_id:
            merged[task_id] = row

    for row in list_active_children_from_registry(session_id):
        task_id = row.get("task_id")
        if isinstance(task_id, str) and task_id and task_id not in merged:
            merged[task_id] = row

    return list(merged.values())


def cancel_active_children_for_session(session_id: str) -> int:
    """Cancel all running children for session_id via ACTIVE_SUBAGENTS (no gateway required)."""
    candidates = _session_id_candidates(session_id)
    if not candidates:
        return 0

    seen_managers: set[int] = set()
    cancelled = 0

    for task_id, manager in list(ACTIVE_SUBAGENTS.items()):
        if _task_session_id(task_id, manager) not in candidates:
            continue
        manager_key = id(manager)
        if manager_key in seen_managers:
            continue
        seen_managers.add(manager_key)
        cancelled += manager.cancel_all()

    return cancelled
