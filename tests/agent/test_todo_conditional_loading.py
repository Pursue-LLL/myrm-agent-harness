"""Tests for todo_write conditional registration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent._skill_agent_tools import SkillAgentToolsMixin
from myrm_agent_harness.agent.skill_agent import SkillAgent
from myrm_agent_harness.backends.skills.types import SkillMetadata


class _TodoHarness(SkillAgentToolsMixin):
    """Minimal harness exposing todo conditional helpers."""

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
        self.config = MagicMock()
        self.llm = MagicMock()


def _sample_skill() -> SkillMetadata:
    return SkillMetadata(
        name="demo",
        description="demo skill",
        model_invocable=True,
        available=True,
    )


@pytest.mark.asyncio
async def test_should_load_todo_when_planning_enabled() -> None:
    harness = _TodoHarness(storage_backend=MagicMock(), enable_planning=True)
    assert await harness._should_load_todo_write_tool() is True


@pytest.mark.asyncio
async def test_should_load_todo_when_workspace_has_todos() -> None:
    harness = _TodoHarness(storage_backend=MagicMock(), enable_planning=False)
    with patch.object(harness, "_workspace_has_todos", new=AsyncMock(return_value=True)):
        assert await harness._should_load_todo_write_tool() is True


@pytest.mark.asyncio
async def test_should_skip_todo_when_disabled_and_no_todos() -> None:
    harness = _TodoHarness(storage_backend=MagicMock(), enable_planning=False)
    with patch.object(harness, "_workspace_has_todos", new=AsyncMock(return_value=False)):
        assert await harness._should_load_todo_write_tool() is False


@pytest.mark.asyncio
async def test_create_todo_write_skipped_without_planning_or_existing_todos() -> None:
    harness = _TodoHarness(storage_backend=MagicMock(), enable_planning=False)
    with patch.object(harness, "_workspace_has_todos", new=AsyncMock(return_value=False)):
        result = await harness._create_todo_write_tool()
    assert result is None


@pytest.mark.asyncio
async def test_create_todo_write_created_when_planning_enabled() -> None:
    harness = _TodoHarness(storage_backend=MagicMock(), enable_planning=True)
    mock_tool = MagicMock(name="todo_write")
    with patch(
        "myrm_agent_harness.agent.meta_tools.progress.todo_write_tool.create_todo_write_tool",
        return_value=mock_tool,
    ) as mock_create:
        result = await harness._create_todo_write_tool()
    assert result is mock_tool
    mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_workspace_has_todos_detects_sandbox_file(tmp_path) -> None:
    workspace = tmp_path / "chat_resume"
    progress_dir = workspace / ".myrm" / "progress"
    progress_dir.mkdir(parents=True)
    progress_dir.joinpath("todos.json").write_text(
        '{"goal":"g","todos":[{"id":"1","content":"step","status":"pending"}]}',
        encoding="utf-8",
    )
    harness = _TodoHarness(
        storage_backend=MagicMock(),
        enable_planning=False,
        task_workspace_root=str(workspace),
    )
    assert await harness._workspace_has_todos() is True
    assert await harness._should_load_todo_write_tool() is True


@pytest.mark.asyncio
async def test_build_tools_excludes_todo_when_planning_disabled() -> None:
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
    assert "todo_write" not in tool_names
