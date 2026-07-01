"""Tests for update_execution_checklist_tool conditional registration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent._skill_agent_tools import SkillAgentToolsMixin


class _ChecklistHarness(SkillAgentToolsMixin):
    def __init__(
        self,
        *,
        storage_backend: object | None,
        task_workspace_root: str | None = None,
        enable_task_tracking: bool = False,
        enable_planning: bool = False,
        user_tools: list[object] | None = None,
    ) -> None:
        self.storage_backend = storage_backend
        self._task_workspace_root = task_workspace_root
        self._enable_task_tracking = enable_task_tracking
        self._enable_planning = enable_planning
        self.user_tools = user_tools or []


@pytest.mark.asyncio
async def test_should_load_checklist_when_task_tracking_enabled() -> None:
    harness = _ChecklistHarness(storage_backend=MagicMock(), enable_task_tracking=True)
    with patch.object(harness, "_workspace_has_plan", new=AsyncMock(return_value=False)):
        assert await harness._should_load_checklist_tool() is True


@pytest.mark.asyncio
async def test_should_not_load_checklist_when_planning_enabled() -> None:
    harness = _ChecklistHarness(
        storage_backend=MagicMock(),
        enable_task_tracking=True,
        enable_planning=True,
    )
    assert await harness._should_load_checklist_tool() is False


@pytest.mark.asyncio
async def test_should_not_load_checklist_when_workspace_has_plan() -> None:
    harness = _ChecklistHarness(storage_backend=MagicMock(), enable_task_tracking=True)
    with patch.object(harness, "_workspace_has_plan", new=AsyncMock(return_value=True)):
        assert await harness._should_load_checklist_tool() is False


@pytest.mark.asyncio
async def test_should_load_checklist_for_existing_file_resume() -> None:
    harness = _ChecklistHarness(storage_backend=MagicMock(), enable_task_tracking=False)
    with patch.object(harness, "_workspace_has_plan", new=AsyncMock(return_value=False)), patch.object(
        harness, "_workspace_has_checklist", new=AsyncMock(return_value=True)
    ):
        assert await harness._should_load_checklist_tool() is True


@pytest.mark.asyncio
async def test_workspace_has_checklist_reads_sandbox_file(tmp_path: Path) -> None:
    workspace = tmp_path / "chat_x"
    checklist_dir = workspace / ".myrm"
    checklist_dir.mkdir(parents=True)
    checklist_dir.joinpath("execution_checklist.json").write_text(
        '{"version":1,"items":[{"id":"1","content":"x","status":"pending"}]}',
        encoding="utf-8",
    )
    harness = _ChecklistHarness(storage_backend=MagicMock(), task_workspace_root=str(workspace))
    assert await harness._workspace_has_checklist() is True


@pytest.mark.asyncio
async def test_create_checklist_tool_skipped_without_tracking_or_file() -> None:
    harness = _ChecklistHarness(storage_backend=MagicMock(), enable_task_tracking=False)
    with patch.object(harness, "_workspace_has_plan", new=AsyncMock(return_value=False)), patch.object(
        harness, "_workspace_has_checklist", new=AsyncMock(return_value=False)
    ):
        result = await harness._create_checklist_tool([])
        assert result is None
