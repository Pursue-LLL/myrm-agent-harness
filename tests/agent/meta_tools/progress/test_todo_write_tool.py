"""Tests for main-agent todo_write tool."""

from __future__ import annotations

import json

import pytest

from myrm_agent_harness.agent.meta_tools.progress.todo_write_tool import create_todo_write_tool


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
async def test_todo_write_requires_workspace() -> None:
    tool = create_todo_write_tool(None)
    result = await tool.ainvoke({"todos": [{"id": "1", "content": "x", "status": "pending"}]})
    payload = json.loads(result)
    assert "error" in payload
