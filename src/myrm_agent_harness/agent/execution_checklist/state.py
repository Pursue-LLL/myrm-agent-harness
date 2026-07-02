"""Execution checklist persistence — lightweight session task tracking.

[INPUT]
- (none — workspace-local filesystem under chat sandbox)

[OUTPUT]
- ChecklistItem, ExecutionChecklistState models
- workspace checklist read/write helpers

[POS]
SSOT for non-Goal, non-planner multi-step execution progress (.myrm/execution_checklist.json).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from contextvars import ContextVar
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

CHECKLIST_STORAGE_REL = ".myrm/execution_checklist.json"
CHECKLIST_STATE_VERSION = 1
CHECKLIST_WORKSPACE_METADATA_KEY = "workspace_root"

_checklist_workspace_hint_var: ContextVar[str] = ContextVar("checklist_workspace_hint", default="")
_checklist_workspace_by_session: dict[str, str] = {}

ChecklistStatus = Literal["pending", "in_progress", "completed", "cancelled"]


class ChecklistItem(BaseModel):
    """Single execution checklist entry."""

    id: str
    content: str
    status: ChecklistStatus = "pending"


class ExecutionChecklistState(BaseModel):
    """Persisted execution checklist for a workspace session."""

    version: int = CHECKLIST_STATE_VERSION
    items: list[ChecklistItem] = Field(default_factory=list)


def checklist_file_path(workspace_root: str) -> Path:
    """Absolute path to checklist JSON under a chat workspace."""
    return Path(workspace_root) / CHECKLIST_STORAGE_REL


def read_checklist_sync(workspace_root: str) -> ExecutionChecklistState | None:
    """Load checklist synchronously (completion_guard path)."""
    path = checklist_file_path(workspace_root)
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return ExecutionChecklistState.model_validate(data)
    except Exception as exc:
        logger.warning("Failed to read execution checklist from %s: %s", path, exc)
        return None


def checklist_exists_sync(workspace_root: str) -> bool:
    """Return True when checklist JSON exists under workspace_root."""
    return checklist_file_path(workspace_root).is_file()


async def save_checklist_to_workspace(workspace_root: str, state: ExecutionChecklistState) -> None:
    """Persist checklist under chat workspace (same path as completion_guard reads)."""
    path = checklist_file_path(workspace_root)
    payload = state.model_dump_json(indent=2)

    def _write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")

    await asyncio.to_thread(_write)


def normalize_checklist_items(raw_items: list[dict[str, object]]) -> list[ChecklistItem]:
    """Validate and normalize LLM-provided checklist items."""
    normalized: list[ChecklistItem] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_items, start=1):
        content = raw.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        item_id = raw.get("id")
        if isinstance(item_id, str) and item_id.strip():
            safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", item_id.strip())[:64] or f"item_{index}"
        else:
            safe_id = f"item_{index}"
        while safe_id in seen_ids:
            safe_id = f"{safe_id}_{index}"
        seen_ids.add(safe_id)

        status_raw = raw.get("status", "pending")
        status: ChecklistStatus = "pending"
        if status_raw in ("pending", "in_progress", "completed", "cancelled"):
            status = status_raw  # type: ignore[assignment]

        normalized.append(ChecklistItem(id=safe_id, content=content.strip(), status=status))
    return normalized


def merge_checklist_by_id(
    existing: list[ChecklistItem],
    incoming: list[ChecklistItem],
) -> list[ChecklistItem]:
    """Merge status/content updates by id; preserve order and unmentioned items."""
    by_id = {item.id: item for item in existing}
    for item in incoming:
        by_id[item.id] = item
    return [by_id[item.id] for item in existing]


def resolve_checklist_items(
    existing: list[ChecklistItem],
    incoming: list[ChecklistItem],
) -> list[ChecklistItem]:
    """Apply a checklist update — full replace or partial merge-by-id."""
    if not existing:
        return incoming
    if len(incoming) >= len(existing):
        return incoming
    return merge_checklist_by_id(existing, incoming)


def incomplete_checklist_items(state: ExecutionChecklistState) -> list[ChecklistItem]:
    """Return items that are not completed or cancelled."""
    return [item for item in state.items if item.status not in ("completed", "cancelled")]


def resolve_checklist_workspace_root(
    *,
    fallback_workspace_root: str | None = None,
    tool_message_workspace_root: str | None = None,
) -> str:
    """Resolve workspace root for checklist read/write across LangGraph context boundaries."""
    if tool_message_workspace_root and tool_message_workspace_root.strip():
        return tool_message_workspace_root.strip()

    hint = _checklist_workspace_hint_var.get()
    if hint:
        return hint

    from myrm_agent_harness.agent.middlewares._session_context import (
        get_approval_session,
        get_workspace_root,
    )

    root = get_workspace_root()
    if root:
        return root

    from myrm_agent_harness.toolkits.code_execution.executors.base import (
        get_executor,
        get_stashed_executor,
    )

    executor = get_executor()
    if executor is not None:
        try:
            return executor.workspace_path
        except RuntimeError:
            pass

    session_id = get_approval_session()
    if session_id:
        cached = _checklist_workspace_by_session.get(session_id)
        if cached:
            return cached
        stashed = get_stashed_executor(session_id)
        if stashed is not None:
            try:
                return stashed.workspace_path
            except RuntimeError:
                pass

    if fallback_workspace_root:
        return fallback_workspace_root
    return ""


def remember_checklist_workspace_root(workspace_root: str) -> None:
    """Record the workspace used by the latest checklist tool invocation."""
    if not workspace_root:
        return
    _checklist_workspace_hint_var.set(workspace_root)
    from myrm_agent_harness.agent.middlewares._session_context import get_approval_session

    session_id = get_approval_session()
    if session_id:
        _checklist_workspace_by_session[session_id] = workspace_root


def clear_checklist_workspace_for_session(session_id: str) -> None:
    """Remove cached checklist workspace root on session teardown."""
    _checklist_workspace_by_session.pop(session_id, None)
    _checklist_workspace_hint_var.set("")
