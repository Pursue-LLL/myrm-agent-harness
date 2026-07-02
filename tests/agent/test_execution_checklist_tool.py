"""Integration tests for execution checklist tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.execution_checklist.tool import create_update_execution_checklist_tool
from myrm_agent_harness.agent.middlewares._session_context import set_workspace_root


@pytest.mark.asyncio
async def test_checklist_tool_writes_to_workspace_not_global(tmp_path: Path) -> None:
    workspace = tmp_path / "sandboxes" / "chat_test"
    workspace.mkdir(parents=True)
    set_workspace_root(str(workspace))

    tool = create_update_execution_checklist_tool()
    result = await tool.ainvoke(
        {
            "todos": [
                {"id": "1", "content": "Research competitors", "status": "in_progress"},
                {"id": "2", "content": "Write summary", "status": "pending"},
            ]
        }
    )
    assert "Checklist updated" in str(result)
    checklist_path = workspace / ".myrm" / "execution_checklist.json"
    assert checklist_path.is_file()
    assert "Research competitors" in checklist_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_completion_guard_sees_workspace_checklist_after_tool_write(tmp_path: Path) -> None:
    from myrm_agent_harness.agent.middlewares.completion_guard import _build_checklist
    from myrm_agent_harness.agent.security.guards.loop_guard_types import CallRecord, SuccessLevel

    workspace = tmp_path / "chat_ws"
    workspace.mkdir()
    set_workspace_root(str(workspace))

    tool = create_update_execution_checklist_tool()
    await tool.ainvoke({"todos": [{"id": "1", "content": "Finish report", "status": "pending"}]})

    records = [
        CallRecord(
            tool_name="file_write_tool",
            args_hash="w1",
            args={"path": "/out/report.md", "content": "x"},
            success_level=SuccessLevel.FULL_SUCCESS,
        ),
    ]
    checklist, has_critical = _build_checklist(records, workspace_root=str(workspace))
    assert has_critical
    assert "Execution checklist has incomplete items" in checklist


@pytest.mark.asyncio
async def test_checklist_tool_merge_by_id_on_partial_update(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    set_workspace_root(str(workspace))

    tool = create_update_execution_checklist_tool()
    await tool.ainvoke(
        {
            "todos": [
                {"id": "a", "content": "Step A", "status": "pending"},
                {"id": "b", "content": "Step B", "status": "pending"},
            ]
        }
    )
    result = await tool.ainvoke({"todos": [{"id": "a", "content": "Step A", "status": "completed"}]})
    assert "1/2 completed" in str(result)
    text = (workspace / ".myrm" / "execution_checklist.json").read_text(encoding="utf-8")
    assert '"status": "completed"' in text
    assert "Step B" in text


@pytest.mark.asyncio
async def test_checklist_tool_errors_without_workspace() -> None:
    from myrm_agent_harness.agent.middlewares._session_context import set_workspace_root

    set_workspace_root("")
    tool = create_update_execution_checklist_tool()
    result = await tool.ainvoke({"todos": [{"content": "Step", "status": "pending"}]})
    assert "workspace root unavailable" in str(result)


@pytest.mark.asyncio
async def test_checklist_tool_rejects_empty_todos(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    set_workspace_root(str(workspace))
    tool = create_update_execution_checklist_tool()
    result = await tool.ainvoke({"todos": [{"content": "  ", "status": "pending"}]})
    assert "at least one item" in str(result)


@pytest.mark.asyncio
async def test_checklist_tool_rejects_multiple_in_progress(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    set_workspace_root(str(workspace))
    tool = create_update_execution_checklist_tool()
    result = await tool.ainvoke(
        {
            "todos": [
                {"content": "A", "status": "in_progress"},
                {"content": "B", "status": "in_progress"},
            ]
        }
    )
    assert "at most one item may be in_progress" in str(result)
