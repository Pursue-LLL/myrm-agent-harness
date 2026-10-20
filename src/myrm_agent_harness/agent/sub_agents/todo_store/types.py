"""
[POS] myrm_agent_harness/agent/sub_agents/todo_store/types.py
[INPUT] dataclasses, typing
[OUTPUT] TodoItemStatus, TodoItem, TodoStoreState, TodoHudProjection, PLAN_DECLARATION_SEMANTIC_NOTE

Core data models and contracts for shared Todo plan store and HUD projections.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

TodoItemStatus = Literal[
    "pending",
    "in_progress",
    "completed",
    "cancelled",
]

# Explicit semantic contract requirement from Oh-My-Hermes / Open-Perplexity specification
PLAN_DECLARATION_SEMANTIC_NOTE: str = (
    "Todo items are plan declarations, not execution evidence."
)


@dataclass
class TodoItem:
    """Individual plan item declaration within shared Todo store."""

    item_id: str
    title: str
    description: str = ""
    status: TodoItemStatus = "pending"
    assignee: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | float]:
        """Serialize Todo item to JSON-compatible dictionary."""
        return {
            "item_id": self.item_id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "assignee": self.assignee,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str | float]) -> TodoItem:
        """Construct TodoItem from serialized dictionary."""
        return cls(
            item_id=str(data.get("item_id", "")),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            status=str(data.get("status", "pending")),  # type: ignore[arg-type]
            assignee=str(data.get("assignee", "")),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )


@dataclass
class TodoStoreState:
    """Collection snapshot of shared Todo items."""

    session_id: str
    items: list[TodoItem] = field(default_factory=list)
    semantic_contract: str = PLAN_DECLARATION_SEMANTIC_NOTE
    updated_at: float = field(default_factory=time.time)


@dataclass
class TodoHudProjection:
    """Read-only sanitized HUD rendering projection for terminal/web surfaces."""

    session_id: str
    total_count: int
    pending_count: int
    in_progress_count: int
    completed_count: int
    cancelled_count: int
    progress_pct: float
    active_items: list[TodoItem]
    formatted_hud_lines: list[str]
    semantic_contract: str = PLAN_DECLARATION_SEMANTIC_NOTE
