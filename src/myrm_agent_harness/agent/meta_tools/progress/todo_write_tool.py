"""Main-agent todo_write tool — deer-flow/Hermes-style progress without sub-agent LLM."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool, tool

from myrm_agent_harness.agent.meta_tools.progress.events import emit_todo_progress_events
from myrm_agent_harness.agent.meta_tools.progress.schemas import TodoStore
from myrm_agent_harness.agent.meta_tools.progress.storage import (
    merge_todo_items,
    parse_todo_payload,
    read_todos_sync_from_workspace,
    write_todos_sync_to_workspace,
)

logger = logging.getLogger(__name__)


def create_todo_write_tool(workspace_root: str | None) -> BaseTool:
    """Create todo_write bound to a chat workspace root."""

    @tool
    def todo_write(
        todos: list[dict[str, Any]],
        merge: bool = False,
        goal: str | None = None,
    ) -> str:
        """Create or update a structured task list for multi-step work.

        Use for complex objectives (typically 3+ steps). Skip for trivial single-step tasks.

        Args:
            todos: List of items with ``id``, ``content``, and optional ``status``
                (pending | in_progress | completed | cancelled).
            merge: When True, update existing items by ``id``; when False, replace the list.
            goal: Optional overall objective label shown in the progress UI root node.

        Returns:
            JSON summary of the current todo list.
        """
        if workspace_root is None or not workspace_root.strip():
            return json.dumps({"error": "Workspace root is not available for todo persistence."})

        root = workspace_root.strip()
        try:
            incoming = parse_todo_payload(todos)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

        current = read_todos_sync_from_workspace(root)
        merged_items = merge_todo_items(current.todos if current else [], incoming, merge=merge)
        store = TodoStore(
            goal=goal if goal is not None else (current.goal if current else None),
            todos=merged_items,
        )
        write_todos_sync_to_workspace(root, store)
        emit_todo_progress_events(store)

        pending = sum(1 for item in store.todos if item.status.value == "pending")
        in_progress = sum(1 for item in store.todos if item.status.value == "in_progress")
        completed = sum(1 for item in store.todos if item.status.value == "completed")
        cancelled = sum(1 for item in store.todos if item.status.value == "cancelled")

        return json.dumps(
            {
                "todos": [item.model_dump() for item in store.todos],
                "summary": {
                    "total": len(store.todos),
                    "pending": pending,
                    "in_progress": in_progress,
                    "completed": completed,
                    "cancelled": cancelled,
                },
            },
            ensure_ascii=False,
        )

    return todo_write


__all__ = ["create_todo_write_tool"]
