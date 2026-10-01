"""Session-tree bound branch state and tool result details replayer.

[INPUT]
- progress.schemas::TodoItem, TodoStatus, TodoStore (POS: models)
- Sequence of message-like objects or dicts with extra_data/details

[OUTPUT]
- fold_branch_todo_state: pure function folding active message branch into authoritative TodoStore
- extract_todo_store_from_payload: safe extractor for tool details or extra_data
- create_compaction_todo_anchor: mono-collapsing anchor snapshot generator for Compaction

[POS]
Replaces global workspace file writes with message-tree bound local state.
Enables true time-travel navigation across branches and atomic rewind.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence

from myrm_agent_harness.agent.meta_tools.progress.schemas import TodoStore

logger = logging.getLogger(__name__)

COMPACTION_TODO_ANCHOR_KEY = "compaction_todo_anchor"
TOOL_DETAILS_KEY = "tool_result_details"
TODO_WRITE_TOOL_NAME = "todo_write"


def extract_todo_store_from_payload(payload: object) -> TodoStore | None:
    """Safely extract TodoStore from dictionary or model payload."""
    if not isinstance(payload, dict):
        return None

    # Case 1: direct TodoStore structure
    if "todos" in payload and isinstance(payload.get("todos"), list):
        try:
            return TodoStore.model_validate(payload)
        except Exception:
            pass

    # Case 2: nested inside tool_result_details
    details = payload.get(TOOL_DETAILS_KEY)
    if isinstance(details, dict):
        nested = extract_todo_store_from_payload(details)
        if nested is not None:
            return nested

    # Case 3: nested inside compaction anchor
    anchor = payload.get(COMPACTION_TODO_ANCHOR_KEY)
    if isinstance(anchor, dict):
        nested = extract_todo_store_from_payload(anchor)
        if nested is not None:
            return nested

    return None


def _get_message_attr(msg: object, key: str) -> object:
    if isinstance(msg, Mapping):
        return msg.get(key)
    return getattr(msg, key, None)


def _extract_todo_from_single_message(msg: object) -> TodoStore | None:
    """Extract TodoStore state emitted by a single message node."""
    extra_data = _get_message_attr(msg, "extra_data")
    if isinstance(extra_data, dict):
        store = extract_todo_store_from_payload(extra_data)
        if store is not None:
            return store

    # Check direct details attribute if available
    details = _get_message_attr(msg, "details")
    if isinstance(details, dict):
        store = extract_todo_store_from_payload(details)
        if store is not None:
            return store

    # Check content if it is a JSON serialized string from todo_write
    content = _get_message_attr(msg, "content")
    if isinstance(content, str) and content.strip().startswith("{") and "todos" in content:
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict) and "todos" in parsed:
                return extract_todo_store_from_payload(parsed)
        except Exception:
            pass

    return None


def fold_branch_todo_state(messages: Sequence[object]) -> TodoStore | None:
    """Fold active message branch into authoritative current TodoStore.

    Traverses from root to active leaf.
    Compaction anchors establish fresh base snapshots; subsequent steps update state.
    """
    if not messages:
        return None

    current_store: TodoStore | None = None

    for msg in messages:
        # 1. Check if message carries a compaction anchor (monotonically collapses history)
        extra_data = _get_message_attr(msg, "extra_data")
        if isinstance(extra_data, dict) and COMPACTION_TODO_ANCHOR_KEY in extra_data:
            anchor_payload = extra_data.get(COMPACTION_TODO_ANCHOR_KEY)
            anchor_store = extract_todo_store_from_payload(anchor_payload)
            if anchor_store is not None:
                current_store = anchor_store

        # 2. Extract potential new todo update from the message
        step_store = _extract_todo_from_single_message(msg)
        if step_store is not None:
            if current_store is None:
                current_store = step_store
            else:
                # Merge or advance revision if step_store is newer
                if step_store.revision >= current_store.revision or not step_store.revision:
                    current_store = step_store

    return current_store


def create_compaction_todo_anchor(store: TodoStore) -> dict[str, object]:
    """Create a collapsed snapshot payload for compaction summary nodes."""
    return {
        COMPACTION_TODO_ANCHOR_KEY: {
            "goal": store.goal,
            "revision": store.revision,
            "todos": [item.model_dump() for item in store.todos],
        }
    }


__all__ = [
    "COMPACTION_TODO_ANCHOR_KEY",
    "TODO_WRITE_TOOL_NAME",
    "TOOL_DETAILS_KEY",
    "create_compaction_todo_anchor",
    "extract_todo_store_from_payload",
    "fold_branch_todo_state",
]
