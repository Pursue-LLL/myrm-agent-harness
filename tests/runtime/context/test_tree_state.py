"""Unit tests for tree_state runtime context replay and isolation."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.progress.schemas import (
    TodoItem,
    TodoStatus,
    TodoStore,
)
from myrm_agent_harness.runtime.context.tree_state import (
    TOOL_DETAILS_KEY,
    create_compaction_todo_anchor,
    extract_todo_store_from_payload,
    fold_branch_todo_state,
)


def test_fold_branch_empty() -> None:
    assert fold_branch_todo_state([]) is None


def test_extract_todo_store_from_payload_direct() -> None:
    raw = {
        "goal": "Test goal",
        "revision": 1,
        "todos": [
            {"id": "1", "content": "Task 1", "status": "pending"},
        ],
    }
    store = extract_todo_store_from_payload(raw)
    assert store is not None
    assert store.goal == "Test goal"
    assert len(store.todos) == 1
    assert store.todos[0].id == "1"


def test_fold_branch_progressive_evolution() -> None:
    msg1 = {
        "id": "m1",
        "extra_data": {
            TOOL_DETAILS_KEY: {
                "goal": "Refactor auth",
                "revision": 1,
                "todos": [
                    {"id": "1", "content": "Research", "status": "in_progress"},
                    {"id": "2", "content": "Code", "status": "pending"},
                ],
            }
        },
    }
    msg2 = {
        "id": "m2",
        "content": "Done with research, starting code",
        "extra_data": {
            TOOL_DETAILS_KEY: {
                "goal": "Refactor auth",
                "revision": 2,
                "todos": [
                    {"id": "1", "content": "Research", "status": "completed"},
                    {"id": "2", "content": "Code", "status": "in_progress"},
                ],
            }
        },
    }

    store = fold_branch_todo_state([msg1, msg2])
    assert store is not None
    assert store.revision == 2
    assert store.todos[0].status == TodoStatus.COMPLETED
    assert store.todos[1].status == TodoStatus.IN_PROGRESS


def test_branch_fork_isolation() -> None:
    """Branch A and Branch B fork from common ancestor msg1; their states remain strictly isolated."""
    msg_common = {
        "id": "m1",
        "extra_data": {
            TOOL_DETAILS_KEY: {
                "goal": "Root goal",
                "revision": 1,
                "todos": [
                    {"id": "1", "content": "Step 1", "status": "completed"},
                    {"id": "2", "content": "Step 2", "status": "pending"},
                ],
            }
        },
    }

    # Branch A advances step 2 with JWT
    msg_branch_a = {
        "id": "m_a",
        "extra_data": {
            TOOL_DETAILS_KEY: {
                "goal": "Root goal (JWT branch)",
                "revision": 2,
                "todos": [
                    {"id": "1", "content": "Step 1", "status": "completed"},
                    {"id": "2", "content": "Step 2: JWT implementation", "status": "in_progress"},
                ],
            }
        },
    }

    # Branch B diverges with Redis Session
    msg_branch_b = {
        "id": "m_b",
        "extra_data": {
            TOOL_DETAILS_KEY: {
                "goal": "Root goal (Session branch)",
                "revision": 2,
                "todos": [
                    {"id": "1", "content": "Step 1", "status": "completed"},
                    {"id": "2", "content": "Step 2: Redis Session", "status": "in_progress"},
                    {"id": "3", "content": "Step 3: Cookie sign", "status": "pending"},
                ],
            }
        },
    }

    store_a = fold_branch_todo_state([msg_common, msg_branch_a])
    store_b = fold_branch_todo_state([msg_common, msg_branch_b])

    assert store_a is not None
    assert store_b is not None
    assert len(store_a.todos) == 2
    assert store_a.todos[1].content == "Step 2: JWT implementation"

    assert len(store_b.todos) == 3
    assert store_b.todos[1].content == "Step 2: Redis Session"
    assert store_b.todos[2].id == "3"


def test_compaction_anchor_survives_truncation() -> None:
    """Historical messages before compaction are evicted, but anchor restores baseline."""
    base_store = TodoStore(
        goal="Long project",
        revision=5,
        todos=[
            TodoItem(id="1", content="Init", status=TodoStatus.COMPLETED),
            TodoItem(id="2", content="Refactor", status=TodoStatus.COMPLETED),
            TodoItem(id="3", content="Test", status=TodoStatus.IN_PROGRESS),
        ],
    )
    anchor_dict = create_compaction_todo_anchor(base_store)

    compaction_summary_node = {
        "id": "summary_node",
        "role": "system",
        "content": "[Context Compacted Summary: Steps 1-2 done, step 3 active]",
        "extra_data": anchor_dict,
    }

    # Subsequent new turn after compaction
    msg_after_compaction = {
        "id": "turn_6",
        "extra_data": {
            TOOL_DETAILS_KEY: {
                "goal": "Long project",
                "revision": 6,
                "todos": [
                    {"id": "1", "content": "Init", "status": "completed"},
                    {"id": "2", "content": "Refactor", "status": "completed"},
                    {"id": "3", "content": "Test", "status": "completed"},
                    {"id": "4", "content": "Deploy", "status": "in_progress"},
                ],
            }
        },
    }

    # Only summary node + subsequent nodes present (historical m1..m5 evicted)
    store = fold_branch_todo_state([compaction_summary_node, msg_after_compaction])
    assert store is not None
    assert store.revision == 6
    assert len(store.todos) == 4
    assert store.todos[2].status == TodoStatus.COMPLETED
    assert store.todos[3].status == TodoStatus.IN_PROGRESS


def test_corrupted_payload_safety() -> None:
    corrupted_msg = {
        "id": "err",
        "extra_data": {"tool_result_details": "invalid_string_not_dict"},
    }
    assert fold_branch_todo_state([corrupted_msg]) is None


def test_emit_todo_progress_events_dispatches_tool_result_details(monkeypatch) -> None:
    """emit_todo_progress_events must dispatch tool_result_details with complete TodoStore."""
    from myrm_agent_harness.agent.meta_tools.progress.events import emit_todo_progress_events

    dispatched: list[tuple[str, dict[str, object]]] = []

    def mock_dispatch(name: str, payload: dict[str, object]) -> None:
        dispatched.append((name, payload))

    monkeypatch.setattr("myrm_agent_harness.agent.meta_tools.progress.events.dispatch_custom_event", mock_dispatch)

    store = TodoStore(
        goal="Feature development",
        revision=3,
        todos=[
            TodoItem(id="1", content="DB schema", status=TodoStatus.COMPLETED),
            TodoItem(id="2", content="API route", status=TodoStatus.IN_PROGRESS),
        ],
    )

    emit_todo_progress_events(store)

    assert len(dispatched) >= 1
    root_event = dispatched[0]
    assert root_event[0] == "tasks_steps"
    payload = root_event[1]
    assert payload.get("tool_name") == "todo_write"
    details = payload.get("tool_result_details")
    assert isinstance(details, dict)
    assert details["goal"] == "Feature development"
    assert details["revision"] == 3
    assert len(details["todos"]) == 2

    # Fold verifying extracted payload
    folded = fold_branch_todo_state([{"extra_data": {"tool_result_details": details}}])
    assert folded is not None
    assert folded.goal == "Feature development"
    assert folded.revision == 3

