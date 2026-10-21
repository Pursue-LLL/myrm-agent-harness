"""
[POS] myrm_agent_harness/agent/sub_agents/todo_store/tools.py
[INPUT] typing.TYPE_CHECKING, langchain.tools.tool, pydantic.BaseModel, pydantic.Field, myrm_agent_harness.agent.sub_agents.todo_store.store, myrm_agent_harness.agent.sub_agents.todo_store.hud_reader
[OUTPUT] create_manage_todo_plan_tool, create_read_todo_hud_tool, get_default_todo_tools

LangChain meta-tools for sub-agents to declare, update, and inspect shared Todo plans and HUD projections.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

from langchain.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.agent.sub_agents.todo_store.hud_reader import (
    SharedTodoHudReader,
)
from myrm_agent_harness.agent.sub_agents.todo_store.store import SharedTodoStore
from myrm_agent_harness.agent.sub_agents.todo_store.types import TodoItemStatus

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

_GLOBAL_TODO_STORE: SharedTodoStore | None = None
_GLOBAL_HUD_READER: SharedTodoHudReader | None = None


def get_default_todo_store() -> SharedTodoStore:
    """Return singleton global instance of SharedTodoStore."""
    global _GLOBAL_TODO_STORE
    if _GLOBAL_TODO_STORE is None:
        _GLOBAL_TODO_STORE = SharedTodoStore(session_id="default")
    return _GLOBAL_TODO_STORE


def get_default_hud_reader() -> SharedTodoHudReader:
    """Return singleton global instance of SharedTodoHudReader."""
    global _GLOBAL_HUD_READER
    if _GLOBAL_HUD_READER is None:
        store = get_default_todo_store()
        _GLOBAL_HUD_READER = SharedTodoHudReader(store)
    return _GLOBAL_HUD_READER


class ManageTodoPlanInput(BaseModel):
    """Input payload for manage_todo_plan tool."""

    action: Literal["add", "update", "remove", "clear"] = Field(
        ...,
        description="Action to perform: 'add' (declare new plan item), 'update' (modify status or text), 'remove' (delete item), 'clear' (empty list).",
    )
    title: str | None = Field(
        default=None,
        description="Plan item title (max 80 chars, required for 'add').",
    )
    description: str | None = Field(
        default=None,
        description="Optional plan details or prerequisites (max 200 chars).",
    )
    status: Literal["pending", "in_progress", "completed", "cancelled"] | None = Field(
        default=None,
        description="Status of the item when updating: 'pending', 'in_progress', 'completed', or 'cancelled'.",
    )
    assignee: str | None = Field(
        default=None,
        description="Assigned role or subagent name (e.g. 'coder', 'researcher', 'architect').",
    )
    item_id: str | None = Field(
        default=None,
        description="Target item ID (required for 'update' and 'remove').",
    )


class ReadTodoHudInput(BaseModel):
    """Input payload for read_todo_hud tool."""

    format: Literal["text", "json"] = Field(
        default="text",
        description="Desired projection format: 'text' (compact terminal HUD lines) or 'json' (structured status metrics).",
    )


def create_manage_todo_plan_tool(store: SharedTodoStore | None = None) -> BaseTool:
    """Create a LangChain tool to manipulate shared Todo plan items."""
    target_store = store or get_default_todo_store()

    @tool("manage_todo_plan", args_schema=ManageTodoPlanInput)
    def manage_todo_plan(
        action: Literal["add", "update", "remove", "clear"],
        title: str | None = None,
        description: str | None = None,
        status: Literal["pending", "in_progress", "completed", "cancelled"] | None = None,
        assignee: str | None = None,
        item_id: str | None = None,
    ) -> str:
        """Declare, update, or remove plan items in the shared Todo plan store.
        Note: Todo items are plan declarations, not execution evidence."""
        try:
            if action == "add":
                if not title:
                    return "Error: 'title' is required when adding a new plan item."
                item = target_store.add_item(
                    title=title,
                    description=description or "",
                    assignee=assignee or "",
                    item_id=item_id or "",
                )
                return f"Plan item added: [{item.item_id}] {item.title} (Status: {item.status})"

            if action == "update":
                if not item_id:
                    return "Error: 'item_id' is required when updating an existing item."
                stat_val: TodoItemStatus | None = status
                updated = target_store.update_item(
                    item_id=item_id,
                    title=title,
                    description=description,
                    status=stat_val,
                    assignee=assignee,
                )
                return f"Plan item updated: [{updated.item_id}] {updated.title} -> {updated.status}"

            if action == "remove":
                if not item_id:
                    return "Error: 'item_id' is required when removing an item."
                removed = target_store.remove_item(item_id)
                if removed:
                    return f"Plan item [{item_id}] removed successfully."
                return f"Item [{item_id}] was not found."

            if action == "clear":
                target_store.clear()
                return "All plan items cleared."

            return f"Unknown action: {action}"
        except Exception as exc:
            return f"Error managing plan item: {exc}"

    return manage_todo_plan


def create_read_todo_hud_tool(reader: SharedTodoHudReader | None = None) -> BaseTool:
    """Create a LangChain tool to inspect the sanitized plan HUD projection."""
    target_reader = reader or get_default_hud_reader()

    @tool("read_todo_hud", args_schema=ReadTodoHudInput)
    def read_todo_hud(format: Literal["text", "json"] = "text") -> str:
        """Inspect the current plan declarations in the shared Todo store.
        Returns terminal-escape safe sanitized summary lines or structured JSON metrics."""
        projection = target_reader.project_hud()
        if format == "json":
            return json.dumps(
                {
                    "session_id": projection.session_id,
                    "total_count": projection.total_count,
                    "pending_count": projection.pending_count,
                    "in_progress_count": projection.in_progress_count,
                    "completed_count": projection.completed_count,
                    "progress_pct": projection.progress_pct,
                    "semantic_contract": projection.semantic_contract,
                    "active_items": [i.to_dict() for i in projection.active_items],
                },
                indent=2,
                ensure_ascii=False,
            )
        return "\n".join(projection.formatted_hud_lines)

    return read_todo_hud


def get_default_todo_tools() -> list[BaseTool]:
    """Return standard suite of Todo plan tools for sub-agents."""
    return [
        create_manage_todo_plan_tool(),
        create_read_todo_hud_tool(),
    ]
