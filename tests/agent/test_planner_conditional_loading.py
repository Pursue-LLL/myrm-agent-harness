"""Tests for planner_tool conditional registration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent._skill_agent_tools import SkillAgentToolsMixin
from myrm_agent_harness.agent.skill_agent import SkillAgent
from myrm_agent_harness.backends.skills.types import SkillMetadata


class _PlannerHarness(SkillAgentToolsMixin):
    """Minimal harness exposing planner conditional helpers."""

    def __init__(
        self,
        *,
        storage_backend: object | None,
        enable_planning: bool = False,
        task_workspace_root: str | None = None,
        user_tools: list[object] | None = None,
    ) -> None:
        self.storage_backend = storage_backend
        self._enable_planning = enable_planning
        self._task_workspace_root = task_workspace_root
        self.user_tools = user_tools or []
        self.config = MagicMock(planner_config=None, max_skills_prompt_chars=12000)
        self.llm = MagicMock()


def _sample_skill() -> SkillMetadata:
    return SkillMetadata(
        name="demo",
        description="demo skill",
        model_invocable=True,
        available=True,
    )


@pytest.mark.asyncio
async def test_should_load_planner_when_planning_enabled() -> None:
    harness = _PlannerHarness(storage_backend=MagicMock(), enable_planning=True)
    assert await harness._should_load_planner_tool() is True


@pytest.mark.asyncio
async def test_should_load_planner_when_workspace_has_plan() -> None:
    harness = _PlannerHarness(storage_backend=MagicMock(), enable_planning=False)
    with patch.object(harness, "_workspace_has_plan", new=AsyncMock(return_value=True)):
        assert await harness._should_load_planner_tool() is True


@pytest.mark.asyncio
async def test_should_skip_planner_when_disabled_and_no_plan() -> None:
    harness = _PlannerHarness(storage_backend=MagicMock(), enable_planning=False)
    with patch.object(harness, "_workspace_has_plan", new=AsyncMock(return_value=False)):
        assert await harness._should_load_planner_tool() is False


@pytest.mark.asyncio
async def test_create_planner_tool_skipped_without_planning_or_existing_plan() -> None:
    harness = _PlannerHarness(storage_backend=MagicMock(), enable_planning=False)
    with patch.object(harness, "_workspace_has_plan", new=AsyncMock(return_value=False)):
        result = await harness._create_planner_tool([_sample_skill()])
    assert result is None


@pytest.mark.asyncio
async def test_create_planner_tool_created_when_planning_enabled() -> None:
    harness = _PlannerHarness(storage_backend=MagicMock(), enable_planning=True)
    mock_tool = MagicMock(name="planner_tool")
    with patch(
        "myrm_agent_harness.agent.sub_agents.planner.planner_agent_tools.create_planner_tool",
        return_value=mock_tool,
    ) as mock_create:
        result = await harness._create_planner_tool([_sample_skill()])
    assert result is mock_tool
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs.get("workspace_root") is None


@pytest.mark.asyncio
async def test_workspace_has_plan_detects_sandbox_plan_file(tmp_path) -> None:
    workspace = tmp_path / "chat_resume"
    plan_dir = workspace / "planner"
    plan_dir.mkdir(parents=True)
    plan_dir.joinpath("plan.json").write_text(
        '{"goal":"g","reasoning":"r","steps":[]}',
        encoding="utf-8",
    )
    harness = _PlannerHarness(
        storage_backend=MagicMock(),
        enable_planning=False,
        task_workspace_root=str(workspace),
    )
    assert await harness._workspace_has_plan() is True
    assert await harness._should_load_planner_tool() is True


@pytest.mark.asyncio
async def test_create_planner_passes_task_workspace_root_to_factory(tmp_path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    harness = _PlannerHarness(
        storage_backend=MagicMock(),
        enable_planning=True,
        task_workspace_root=str(workspace),
    )
    mock_tool = MagicMock(name="planner_tool")
    with patch(
        "myrm_agent_harness.agent.sub_agents.planner.planner_agent_tools.create_planner_tool",
        return_value=mock_tool,
    ) as mock_create:
        await harness._create_planner_tool([_sample_skill()])
    assert mock_create.call_args.kwargs.get("workspace_root") == str(workspace)


@pytest.mark.asyncio
async def test_build_tools_excludes_planner_when_planning_disabled() -> None:
    """Integration: resolved tool list must not contain planner_tool by default."""
    mock_llm = AsyncMock()
    storage = MagicMock()

    async def mock_exists(_path: str) -> bool:
        return False

    storage.exists = mock_exists

    agent = SkillAgent(
        llm=mock_llm,
        storage_backend=storage,
        enable_planning=False,
        enable_file_tools=False,
        enable_bash=False,
        enable_answer_tool=False,
    )
    agent.skill_backend = AsyncMock()
    agent.skill_backend.list_skills.return_value = [_sample_skill()]

    tools = await agent._build_tools()
    tool_names = [t.name for t in tools]
    assert "planner_tool" not in tool_names
