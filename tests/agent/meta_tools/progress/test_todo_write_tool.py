"""Tests for main-agent todo_write tool."""

from __future__ import annotations

import json

import pytest

from myrm_agent_harness.agent.meta_tools.progress.schemas import MAX_TODOS, TodoItem, TodoStatus
from myrm_agent_harness.agent.meta_tools.progress.todo_write_tool import (
    _enforce_single_in_progress,
    create_todo_write_tool,
)


@pytest.mark.asyncio
async def test_todo_write_replace_and_merge(tmp_path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    tool = create_todo_write_tool(str(workspace))

    first = await tool.ainvoke(
        {
            "todos": [
                {"id": "1", "content": "Read code", "status": "in_progress"},
                {"id": "2", "content": "Apply patch", "status": "pending"},
            ],
            "merge": False,
            "goal": "OAuth migration",
        }
    )
    first_data = json.loads(first)
    assert first_data["summary"]["total"] == 2

    second = await tool.ainvoke(
        {
            "todos": [
                {"id": "1", "content": "Read code", "status": "completed"},
                {"id": "2", "content": "Apply patch", "status": "in_progress"},
            ],
            "merge": True,
        }
    )
    second_data = json.loads(second)
    assert second_data["summary"]["completed"] == 1
    assert second_data["summary"]["in_progress"] == 1

    todos_file = workspace / ".myrm" / "progress" / "todos.json"
    assert todos_file.is_file()


@pytest.mark.asyncio
async def test_todo_write_returns_error_on_invalid_status(tmp_path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    tool = create_todo_write_tool(str(workspace))
    result = await tool.ainvoke(
        {
            "todos": [{"id": "1", "content": "bad", "status": "not-a-status"}],
            "merge": False,
        }
    )
    error_payload = json.loads(result)
    assert "error" in error_payload


@pytest.mark.asyncio
async def test_todo_write_requires_workspace() -> None:
    tool = create_todo_write_tool(None)
    result = await tool.ainvoke({"todos": [{"id": "1", "content": "x", "status": "pending"}]})
    payload = json.loads(result)
    assert "error" in payload


# ---------------------------------------------------------------------------
# Module 2: MAX_TODOS upper-limit constraint
# ---------------------------------------------------------------------------


def _make_todos(n: int, *, status: str = "pending") -> list[dict[str, str]]:
    return [{"id": str(i), "content": f"task-{i}", "status": status} for i in range(n)]


@pytest.mark.asyncio
async def test_todo_write_rejects_over_max(tmp_path) -> None:
    """Exceeding MAX_TODOS returns an error without persisting."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    tool = create_todo_write_tool(str(workspace))

    result = await tool.ainvoke({"todos": _make_todos(MAX_TODOS + 1), "merge": False})
    data = json.loads(result)
    assert "error" in data
    assert str(MAX_TODOS) in data["error"]

    todos_file = workspace / ".myrm" / "progress" / "todos.json"
    assert not todos_file.exists()


@pytest.mark.asyncio
async def test_todo_write_accepts_exactly_max(tmp_path) -> None:
    """Exactly MAX_TODOS items should succeed."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    tool = create_todo_write_tool(str(workspace))

    result = await tool.ainvoke({"todos": _make_todos(MAX_TODOS), "merge": False})
    data = json.loads(result)
    assert "error" not in data
    assert data["summary"]["total"] == MAX_TODOS


@pytest.mark.asyncio
async def test_todo_write_merge_exceeds_max(tmp_path) -> None:
    """Merge that produces > MAX_TODOS total should be rejected."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    tool = create_todo_write_tool(str(workspace))

    await tool.ainvoke({"todos": _make_todos(MAX_TODOS), "merge": False})

    extra = [{"id": "new-extra", "content": "overflow task", "status": "pending"}]
    result = await tool.ainvoke({"todos": extra, "merge": True})
    data = json.loads(result)
    assert "error" in data
    assert str(MAX_TODOS) in data["error"]


# ---------------------------------------------------------------------------
# Module 2: single in_progress enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_todo_write_single_in_progress_no_correction(tmp_path) -> None:
    """One in_progress item — no correction, no note."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    tool = create_todo_write_tool(str(workspace))

    result = await tool.ainvoke({
        "todos": [
            {"id": "a", "content": "step-a", "status": "in_progress"},
            {"id": "b", "content": "step-b", "status": "pending"},
        ],
        "merge": False,
    })
    data = json.loads(result)
    assert data["summary"]["in_progress"] == 1
    assert "note" not in data["summary"]


@pytest.mark.asyncio
async def test_todo_write_multiple_in_progress_corrected(tmp_path) -> None:
    """Multiple in_progress items — only the last survives, note is present."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    tool = create_todo_write_tool(str(workspace))

    result = await tool.ainvoke({
        "todos": [
            {"id": "a", "content": "step-a", "status": "in_progress"},
            {"id": "b", "content": "step-b", "status": "in_progress"},
            {"id": "c", "content": "step-c", "status": "in_progress"},
        ],
        "merge": False,
    })
    data = json.loads(result)
    assert data["summary"]["in_progress"] == 1
    assert data["summary"]["pending"] == 2
    assert "note" in data["summary"]
    assert "2" in data["summary"]["note"]

    last_ip = [t for t in data["todos"] if t["status"] == "in_progress"]
    assert len(last_ip) == 1
    assert last_ip[0]["id"] == "c"


@pytest.mark.asyncio
async def test_todo_write_merge_creates_duplicate_in_progress(tmp_path) -> None:
    """Merge that adds a second in_progress item — auto-corrects the first."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    tool = create_todo_write_tool(str(workspace))

    await tool.ainvoke({
        "todos": [
            {"id": "x", "content": "first", "status": "in_progress"},
            {"id": "y", "content": "second", "status": "pending"},
        ],
        "merge": False,
    })

    result = await tool.ainvoke({
        "todos": [{"id": "y", "content": "second", "status": "in_progress"}],
        "merge": True,
    })
    data = json.loads(result)
    assert data["summary"]["in_progress"] == 1
    assert data["summary"]["note"] is not None

    ip_items = [t for t in data["todos"] if t["status"] == "in_progress"]
    assert len(ip_items) == 1
    assert ip_items[0]["id"] == "y"


# ---------------------------------------------------------------------------
# Unit tests for _enforce_single_in_progress helper
# ---------------------------------------------------------------------------


class TestEnforceSingleInProgress:
    def test_empty_list(self) -> None:
        items: list[TodoItem] = []
        assert _enforce_single_in_progress(items) == 0

    def test_no_in_progress(self) -> None:
        items = [
            TodoItem(id="1", content="a", status=TodoStatus.PENDING),
            TodoItem(id="2", content="b", status=TodoStatus.COMPLETED),
        ]
        assert _enforce_single_in_progress(items) == 0

    def test_one_in_progress(self) -> None:
        items = [TodoItem(id="1", content="a", status=TodoStatus.IN_PROGRESS)]
        assert _enforce_single_in_progress(items) == 0
        assert items[0].status == TodoStatus.IN_PROGRESS

    def test_three_in_progress_keeps_last(self) -> None:
        items = [
            TodoItem(id="1", content="a", status=TodoStatus.IN_PROGRESS),
            TodoItem(id="2", content="b", status=TodoStatus.PENDING),
            TodoItem(id="3", content="c", status=TodoStatus.IN_PROGRESS),
            TodoItem(id="4", content="d", status=TodoStatus.IN_PROGRESS),
        ]
        corrected = _enforce_single_in_progress(items)
        assert corrected == 2
        assert items[0].status == TodoStatus.PENDING
        assert items[2].status == TodoStatus.PENDING
        assert items[3].status == TodoStatus.IN_PROGRESS
