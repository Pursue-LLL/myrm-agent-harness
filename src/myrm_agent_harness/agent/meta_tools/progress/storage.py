"""Workspace SSOT for session todos (`.myrm/progress/todos.json`).

[INPUT]
- progress.schemas::TodoItem, TodoStore (POS: models)
- infra.atomic_write::atomic_write (POS: crash-safe writes)

[OUTPUT]
- read/write/merge todos under workspace `.myrm/progress/`
- todos_path, workspace_todos_exist helpers

[POS]
Persists main-agent todo state in chat workspace (atomic JSON).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from myrm_agent_harness.agent.meta_tools.progress.schemas import TodoItem, TodoStatus, TodoStore
from myrm_agent_harness.infra.atomic_write import atomic_write

logger = logging.getLogger(__name__)

PROGRESS_RELATIVE_DIR = ".myrm/progress"
TODOS_FILENAME = "todos.json"


def todos_path(workspace_root: str) -> Path:
    return Path(workspace_root) / PROGRESS_RELATIVE_DIR / TODOS_FILENAME


def read_todos_sync_from_workspace(workspace_root: str) -> TodoStore | None:
    path = todos_path(workspace_root)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        return TodoStore.model_validate(raw)
    except Exception as exc:
        logger.warning("Failed to read todos from %s: %s", path, exc)
        return None


def write_todos_sync_to_workspace(workspace_root: str, store: TodoStore) -> None:
    path = todos_path(workspace_root)
    atomic_write(path, store.model_dump_json(indent=2))


async def workspace_todos_exist(storage_backend: object, *, workspace_root: str | None) -> bool:
    if not workspace_root:
        return False
    path = todos_path(workspace_root)
    exists_fn = getattr(storage_backend, "exists", None)
    if callable(exists_fn):
        try:
            rel_key = f"{PROGRESS_RELATIVE_DIR}/{TODOS_FILENAME}"
            if await exists_fn(rel_key):
                return True
        except Exception as exc:
            logger.warning("Failed to check todos existence via storage backend: %s", exc)
    return path.is_file()


def delete_todos_sync_from_workspace(workspace_root: str) -> None:
    path = todos_path(workspace_root)
    if path.is_file():
        path.unlink()


def merge_todo_items(
    current: list[TodoItem],
    incoming: list[TodoItem],
    *,
    merge: bool,
) -> list[TodoItem]:
    """Merge incoming items with existing ones.

    When merge=False, replaces the list with incoming items (which must each have valid content).
    When merge=True, updates existing items by id (inheriting previous content/status if omitted)
    or appends newly created items.
    """
    if not merge:
        for idx, item in enumerate(incoming):
            if not item.content:
                msg = f"todos[{idx}].content is required when initializing or replacing task list"
                raise ValueError(msg)
        return incoming

    by_id = {item.id: item for item in current}
    order: list[str] = [item.id for item in current]

    for idx, item in enumerate(incoming):
        if item.id in by_id:
            old_item = by_id[item.id]
            resolved_content = item.content if item.content else old_item.content
            resolved_status = item.status
            by_id[item.id] = TodoItem(id=item.id, content=resolved_content, status=resolved_status)
        else:
            if not item.content:
                msg = f"todos[{idx}].content is required for new item with id '{item.id}'"
                raise ValueError(msg)
            order.append(item.id)
            by_id[item.id] = item

    return [by_id[item_id] for item_id in order if item_id in by_id]


def parse_todo_payload(raw_items: list[object], *, allow_empty_content: bool = False) -> list[TodoItem]:
    """Parse raw todo objects into validated TodoItem instances.

    Args:
        raw_items: Raw list of dictionaries from tool arguments.
        allow_empty_content: When True (used in merge mode), content may be empty to allow
            partial status-only updates for existing items.
    """
    parsed: list[TodoItem] = []
    valid_statuses_str = ", ".join(f"'{s.value}'" for s in TodoStatus)

    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            msg = f"todos[{index}] must be an object"
            raise ValueError(msg)
        item_id = str(raw.get("id", "")).strip()
        content = str(raw.get("content", "")).strip()
        if not item_id:
            msg = f"todos[{index}].id is required"
            raise ValueError(msg)
        if not content and not allow_empty_content:
            msg = f"todos[{index}].content is required"
            raise ValueError(msg)
        status_raw = str(raw.get("status", TodoStatus.PENDING.value)).strip()
        try:
            status = TodoStatus(status_raw)
        except ValueError as exc:
            msg = f"todos[{index}].status '{status_raw}' is invalid. Valid statuses are: [{valid_statuses_str}]"
            raise ValueError(msg) from exc
        parsed.append(TodoItem(id=item_id, content=content, status=status))
    return parsed
