"""
[POS] tests/agent/sub_agents/test_shared_todo_store.py
[INPUT] pytest, pathlib.Path, json, myrm_agent_harness.agent.sub_agents.todo_store
[OUTPUT] test_strip_control_characters_and_ansi, test_todo_store_capacity_and_length_bounds, test_todo_store_crud_and_disk_atomic_persistence, test_hud_reader_projection_and_metrics, test_langchain_tools_execution

Unit test suite for shared Todo plan store and terminal-escape safe HUD reader.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myrm_agent_harness.agent.sub_agents.todo_store import (
    MAX_DESCRIPTION_LENGTH,
    MAX_TITLE_LENGTH,
    MAX_TODO_ITEMS,
    PLAN_DECLARATION_SEMANTIC_NOTE,
    SharedTodoHudReader,
    SharedTodoStore,
    create_manage_todo_plan_tool,
    create_read_todo_hud_tool,
    strip_control_characters,
)


def test_strip_control_characters_and_ansi() -> None:
    """Verify bidirectional C0/C1 and ANSI escape sequence stripping."""
    # ANSI color codes
    ansi_dirty = "\x1b[31;1mDangerous Plan\x1b[0m"
    assert strip_control_characters(ansi_dirty) == "Dangerous Plan"

    # C0 control characters (BEL, BS, NUL, ESC, etc.)
    c0_dirty = "Deploy\x00to\x07production\x08cluster\x1b[2K"
    assert strip_control_characters(c0_dirty) == "Deploy to production cluster"

    # C1 control characters (0x80 - 0x9F)
    c1_dirty = "Run\x80benchmarks\x90now"
    assert strip_control_characters(c1_dirty) == "Run benchmarks now"

    # Newlines and carriage returns collapsed to clean single line
    newline_dirty = "First line\r\nSecond line\n\nThird line"
    assert strip_control_characters(newline_dirty) == "First line Second line Third line"

    # Edge cases
    assert strip_control_characters("") == ""
    assert strip_control_characters("   ") == ""


def test_todo_store_capacity_and_length_bounds() -> None:
    """Verify capacity cap (20 items) and string length bounds enforcement."""
    store = SharedTodoStore(session_id="bounds-test")

    # Title exceeds 80 characters: truncated cleanly
    long_title = "A" * 120
    item = store.add_item(title=long_title)
    assert len(item.title) == MAX_TITLE_LENGTH

    # Description exceeds 200 characters: truncated cleanly
    long_desc = "B" * 300
    item2 = store.add_item(title="Task 2", description=long_desc)
    assert len(item2.description) == MAX_DESCRIPTION_LENGTH

    # Empty title rejected
    with pytest.raises(ValueError, match="cannot be empty"):
        store.add_item(title="   \x07\x00   ")

    # Fill up to MAX_TODO_ITEMS (2 already added, add 18 more)
    for i in range(3, MAX_TODO_ITEMS + 1):
        store.add_item(title=f"Task {i}")

    assert len(store.get_items()) == MAX_TODO_ITEMS

    # Adding 21st item exceeds capacity
    with pytest.raises(ValueError, match="capacity exceeded"):
        store.add_item(title="Task 21 will fail")


def test_todo_store_crud_and_disk_atomic_persistence(tmp_path: Path) -> None:
    """Verify CRUD lifecycle and bidirectional disk sanitization."""
    storage_file = tmp_path / "runtime" / "todo.json"
    store = SharedTodoStore(session_id="sess-crud", storage_path=storage_file)

    # 1. Add items
    t1 = store.add_item(title="Scaffold backend API", assignee="architect")
    t2 = store.add_item(title="Write unit tests", assignee="tester")
    assert storage_file.exists()

    # 2. Update item
    updated_t1 = store.update_item(
        item_id=t1.item_id,
        status="in_progress",
        description="Implementing FastAPI endpoints",
    )
    assert updated_t1.status == "in_progress"

    # 3. Simulate another process modifying file with injected ANSI dirty bytes
    raw_content = json.loads(storage_file.read_text(encoding="utf-8"))
    raw_content["items"].append(
        {
            "item_id": "injected-01",
            "title": "\x1b[33mPoisoned\x1b[0m Task\x07",
            "description": "Injected\x00desc",
            "status": "pending",
            "assignee": "\x1b[1madmin\x1b[0m",
            "created_at": 1000.0,
            "updated_at": 1000.0,
        }
    )
    storage_file.write_text(json.dumps(raw_content), encoding="utf-8")

    # 4. Reload from disk and verify read-boundary sanitization
    store_reloaded = SharedTodoStore(session_id="sess-crud", storage_path=storage_file)
    injected_item = store_reloaded.get_item("injected-01")
    assert injected_item is not None
    assert injected_item.title == "Poisoned Task"
    assert injected_item.description == "Injected desc"
    assert injected_item.assignee == "admin"

    # 5. Semantic note contract check
    state = store_reloaded.get_state()
    assert state.semantic_contract == PLAN_DECLARATION_SEMANTIC_NOTE

    # 6. Remove and clear
    removed = store_reloaded.remove_item(t2.item_id)
    assert removed is True
    assert store_reloaded.get_item(t2.item_id) is None

    store_reloaded.clear()
    assert len(store_reloaded.get_items()) == 0


def test_hud_reader_projection_and_metrics() -> None:
    """Verify HUD projection calculation and terminal line rendering."""
    store = SharedTodoStore(session_id="hud-test")
    reader = SharedTodoHudReader(store)

    # Empty projection
    empty_proj = reader.project_hud()
    assert empty_proj.total_count == 0
    assert empty_proj.progress_pct == 0.0
    assert "[PLAN HUD] No active plan declarations." in empty_proj.formatted_hud_lines

    # Add 3 items: 1 completed, 1 in_progress, 1 pending
    store.add_item(title="System architecture design", assignee="architect")
    store.add_item(title="Implement core logic", assignee="coder")
    store.add_item(title="Run integration tests", assignee="qa")

    items = store.get_items()
    store.update_item(item_id=items[0].item_id, status="completed")
    store.update_item(item_id=items[1].item_id, status="in_progress")

    proj = reader.project_hud()
    assert proj.total_count == 3
    assert proj.completed_count == 1
    assert proj.in_progress_count == 1
    assert proj.pending_count == 1
    assert proj.progress_pct == 33.3
    assert len(proj.active_items) == 2  # coder (in_progress) and qa (pending)

    # Check formatted lines
    compact_text = reader.render_compact_text()
    assert "[PLAN HUD] Progress: 33.3%" in compact_text
    assert "[x] 1. System architecture design @architect" in compact_text
    assert "[>] 2. Implement core logic @coder" in compact_text
    assert "[ ] 3. Run integration tests @qa" in compact_text
    assert PLAN_DECLARATION_SEMANTIC_NOTE in compact_text


def test_langchain_tools_execution() -> None:
    """Verify manage_todo_plan and read_todo_hud LangChain tools."""
    store = SharedTodoStore(session_id="tools-test")
    reader = SharedTodoHudReader(store)

    manage_tool = create_manage_todo_plan_tool(store)
    read_tool = create_read_todo_hud_tool(reader)

    # 1. Add item via tool
    add_res = manage_tool.invoke(
        {
            "action": "add",
            "title": "Build distributed consensus",
            "assignee": "orchestrator",
            "item_id": "plan-node-01",
        }
    )
    assert "Plan item added: [plan-node-01]" in add_res
    assert store.get_item("plan-node-01") is not None

    # 2. Read HUD as text
    text_hud = read_tool.invoke({"format": "text"})
    assert "[PLAN HUD] Progress: 0.0%" in text_hud
    assert "Build distributed consensus @orchestrator" in text_hud

    # 3. Read HUD as JSON
    json_hud = read_tool.invoke({"format": "json"})
    hud_data = json.loads(json_hud)
    assert hud_data["total_count"] == 1
    assert hud_data["active_items"][0]["item_id"] == "plan-node-01"

    # 4. Update item via tool
    update_res = manage_tool.invoke(
        {
            "action": "update",
            "item_id": "plan-node-01",
            "status": "completed",
        }
    )
    assert "Plan item updated: [plan-node-01]" in update_res
    assert store.get_item("plan-node-01").status == "completed"

    # 5. Remove and clear
    del_res = manage_tool.invoke({"action": "remove", "item_id": "plan-node-01"})
    assert "removed successfully" in del_res
    assert store.get_item("plan-node-01") is None

    clear_res = manage_tool.invoke({"action": "clear"})
    assert "All plan items cleared" in clear_res
