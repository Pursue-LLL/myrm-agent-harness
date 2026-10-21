"""
[POS] myrm_agent_harness/agent/sub_agents/todo_store/store.py
[INPUT] json, os, pathlib, threading, time, uuid, myrm_agent_harness.agent.sub_agents.todo_store.sanitizer, myrm_agent_harness.agent.sub_agents.todo_store.types
[OUTPUT] SharedTodoStore, MAX_TODO_ITEMS, MAX_TITLE_LENGTH, MAX_DESCRIPTION_LENGTH

Thread-safe, cross-process shared Todo plan store with bidirectional control character sanitization.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from myrm_agent_harness.agent.sub_agents.todo_store.sanitizer import (
    sanitize_todo_text,
)
from myrm_agent_harness.agent.sub_agents.todo_store.types import (
    PLAN_DECLARATION_SEMANTIC_NOTE,
    TodoItem,
    TodoItemStatus,
    TodoStoreState,
)

MAX_TODO_ITEMS: int = 20
MAX_TITLE_LENGTH: int = 80
MAX_DESCRIPTION_LENGTH: int = 200


class SharedTodoStore:
    """
    Thread-safe shared Todo store for plan declarations across sub-agents and plugins.
    Enforces maximum capacity (20 items), string bounds, and bidirectional C0/C1 stripping.
    """

    def __init__(
        self,
        session_id: str = "global",
        storage_path: Path | None = None,
    ) -> None:
        self.session_id = session_id
        self.storage_path = storage_path
        self._lock = threading.Lock()
        self._items: list[TodoItem] = []
        self._updated_at: float = time.time()

        if self.storage_path is not None and self.storage_path.exists():
            self.load_from_file()

    def add_item(
        self,
        title: str,
        description: str = "",
        assignee: str = "",
        item_id: str = "",
    ) -> TodoItem:
        """Add a new plan declaration item, strictly sanitizing and bounding length."""
        with self._lock:
            if len(self._items) >= MAX_TODO_ITEMS:
                raise ValueError(
                    f"Todo store capacity exceeded: maximum allowed items is {MAX_TODO_ITEMS}."
                )

            clean_title = sanitize_todo_text(title, MAX_TITLE_LENGTH)
            if not clean_title:
                raise ValueError("Todo item title cannot be empty or purely control characters.")

            clean_desc = sanitize_todo_text(description, MAX_DESCRIPTION_LENGTH)
            clean_assignee = sanitize_todo_text(assignee, 40)
            clean_id = sanitize_todo_text(item_id, 40) or f"todo-{uuid.uuid4().hex[:8]}"

            # Disallow duplicate item ID
            for existing in self._items:
                if existing.item_id == clean_id:
                    raise ValueError(f"Todo item with id '{clean_id}' already exists.")

            now = time.time()
            item = TodoItem(
                item_id=clean_id,
                title=clean_title,
                description=clean_desc,
                status="pending",
                assignee=clean_assignee,
                created_at=now,
                updated_at=now,
            )
            self._items.append(item)
            self._updated_at = now

            if self.storage_path is not None:
                self._save_to_file_locked()

            return item

    def update_item(
        self,
        item_id: str,
        title: str | None = None,
        description: str | None = None,
        status: TodoItemStatus | None = None,
        assignee: str | None = None,
    ) -> TodoItem:
        """Update fields of an existing Todo item."""
        with self._lock:
            target: TodoItem | None = None
            for item in self._items:
                if item.item_id == item_id:
                    target = item
                    break

            if target is None:
                raise KeyError(f"Todo item '{item_id}' not found.")

            now = time.time()
            if title is not None:
                clean_title = sanitize_todo_text(title, MAX_TITLE_LENGTH)
                if clean_title:
                    target.title = clean_title
            if description is not None:
                target.description = sanitize_todo_text(description, MAX_DESCRIPTION_LENGTH)
            if status is not None:
                target.status = status
            if assignee is not None:
                target.assignee = sanitize_todo_text(assignee, 40)

            target.updated_at = now
            self._updated_at = now

            if self.storage_path is not None:
                self._save_to_file_locked()

            return target

    def remove_item(self, item_id: str) -> bool:
        """Remove a Todo item by ID."""
        with self._lock:
            original_len = len(self._items)
            self._items = [i for i in self._items if i.item_id != item_id]
            removed = len(self._items) < original_len
            if removed:
                self._updated_at = time.time()
                if self.storage_path is not None:
                    self._save_to_file_locked()
            return removed

    def get_items(self) -> list[TodoItem]:
        """Retrieve copy of all items in store."""
        with self._lock:
            return list(self._items)

    def get_item(self, item_id: str) -> TodoItem | None:
        """Get single item by ID."""
        with self._lock:
            for item in self._items:
                if item.item_id == item_id:
                    return item
            return None

    def clear(self) -> None:
        """Clear all items."""
        with self._lock:
            self._items.clear()
            self._updated_at = time.time()
            if self.storage_path is not None:
                self._save_to_file_locked()

    def get_state(self) -> TodoStoreState:
        """Retrieve full store state snapshot."""
        with self._lock:
            return TodoStoreState(
                session_id=self.session_id,
                items=list(self._items),
                semantic_contract=PLAN_DECLARATION_SEMANTIC_NOTE,
                updated_at=self._updated_at,
            )

    def load_from_file(self) -> None:
        """Load state from file, applying bidirectional sanitation filter on read."""
        if self.storage_path is None or not self.storage_path.exists():
            return

        with self._lock:
            try:
                raw_text = self.storage_path.read_text(encoding="utf-8")
                payload = json.loads(raw_text)
                if not isinstance(payload, dict):
                    return
                raw_items = payload.get("items", [])
                loaded_items: list[TodoItem] = []
                for entry in raw_items:
                    if isinstance(entry, dict):
                        # Re-sanitize on read to ensure clean boundary
                        clean_title = sanitize_todo_text(str(entry.get("title", "")), MAX_TITLE_LENGTH)
                        clean_desc = sanitize_todo_text(str(entry.get("description", "")), MAX_DESCRIPTION_LENGTH)
                        clean_assignee = sanitize_todo_text(str(entry.get("assignee", "")), 40)
                        clean_id = sanitize_todo_text(str(entry.get("item_id", "")), 40)
                        clean_status = str(entry.get("status", "pending"))
                        if clean_status not in ("pending", "in_progress", "completed", "cancelled"):
                            clean_status = "pending"

                        if clean_title:
                            loaded_items.append(
                                TodoItem(
                                    item_id=clean_id,
                                    title=clean_title,
                                    description=clean_desc,
                                    status=clean_status,  # type: ignore[arg-type]
                                    assignee=clean_assignee,
                                    created_at=float(entry.get("created_at", time.time())),
                                    updated_at=float(entry.get("updated_at", time.time())),
                                )
                            )
                self._items = loaded_items[:MAX_TODO_ITEMS]
                self._updated_at = float(payload.get("updated_at", time.time()))
            except Exception:
                # Fail-safe fallback on corrupt json
                pass

    def _save_to_file_locked(self) -> None:
        """Atomic write to storage path."""
        if self.storage_path is None:
            return

        payload = {
            "session_id": self.session_id,
            "semantic_contract": PLAN_DECLARATION_SEMANTIC_NOTE,
            "updated_at": self._updated_at,
            "items": [item.to_dict() for item in self._items],
        }
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.storage_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temp_path, self.storage_path)
