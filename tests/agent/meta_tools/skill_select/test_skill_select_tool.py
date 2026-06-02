"""Tests for skill_select_tool: reload summary and loaded-skill deduplication."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.skills.select.skill_select_tool import (
    _build_reload_summary,
    create_select_skill_tool,
)
from myrm_agent_harness.backends.skills.types import MCPSkillData, SkillMetadata

_DEFAULT_TOOLS = ["tool_a", "tool_b"]


def _make_mcp_skill(
    name: str = "test_mcp_skill",
    tools: list[str] | None = None,
    tool_schemas: dict[str, dict[str, object]] | None = None,
) -> SkillMetadata:
    resolved_tools = tools if tools is not None else list(_DEFAULT_TOOLS)
    resolved_schemas = (
        tool_schemas
        if tool_schemas is not None
        else {t: {"type": "object"} for t in resolved_tools}
    )
    return SkillMetadata(
        name=name,
        description="Test MCP skill",
        mcp=MCPSkillData(
            server="test_server",
            tools=resolved_tools,
            config=[],
            tool_schemas=resolved_schemas,
        ),
    )


def _make_storage_skill(name: str = "test_storage_skill") -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description="Test storage skill",
        storage_skill_id="storage_123",
        storage_path="/skills/test",
    )


class TestBuildReloadSummary:
    """Tests for _build_reload_summary function."""

    def test_mcp_skill_includes_tool_names(self) -> None:
        skill = _make_mcp_skill(tools=["search_tool", "fetch_tool", "parse_tool"])
        result = _build_reload_summary(skill)

        assert "already loaded" in result
        assert "search_tool" in result
        assert "fetch_tool" in result
        assert "parse_tool" in result

    def test_mcp_skill_limits_tool_names_to_20(self) -> None:
        tools = [f"tool_{i}" for i in range(30)]
        skill = _make_mcp_skill(tools=tools)
        result = _build_reload_summary(skill)

        assert "tool_0" in result
        assert "tool_19" in result
        assert "tool_20" not in result

    def test_non_mcp_skill_no_tools_section(self) -> None:
        skill = _make_storage_skill()
        result = _build_reload_summary(skill)

        assert "already loaded" in result
        assert "Available tools" not in result

    def test_mcp_skill_empty_tools_list(self) -> None:
        skill = _make_mcp_skill(tools=[])
        result = _build_reload_summary(skill)

        assert "already loaded" in result
        assert "Available tools" not in result

    def test_output_contains_skill_name(self) -> None:
        skill = _make_mcp_skill(name="my_custom_skill")
        result = _build_reload_summary(skill)

        assert "my_custom_skill" in result

    def test_output_suggests_bash_execution(self) -> None:
        skill = _make_mcp_skill()
        result = _build_reload_summary(skill)

        assert "bash_code_execute_tool" in result

    def test_output_suggests_file_read_for_full_sop(self) -> None:
        skill = _make_mcp_skill()
        result = _build_reload_summary(skill)

        assert "file_read_tool" in result


class TestCreateSelectSkillToolDeduplication:
    """Tests for loaded-skill deduplication in select_skill_func."""

    @pytest.mark.asyncio
    async def test_first_load_returns_full_sop(self) -> None:
        skill = _make_mcp_skill(name="mcp_search_skill")
        backend = AsyncMock()

        with (
            patch(
                "myrm_agent_harness.agent._skill_agent_context.get_loaded_skills",
                return_value=[],
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.skills.select.skill_select_tool.get_skill_document",
                return_value="# Full SOP document\nStep 1: Do this\nStep 2: Do that",
            ) as mock_get_doc,
            patch(
                "myrm_agent_harness.agent._skill_agent_context.add_loaded_skill",
            ) as mock_add,
        ):
            tool = create_select_skill_tool([skill], backend)
            result = await tool.ainvoke(
                {"skill_names": ["mcp_search_skill"], "reason": "testing"}
            )

            mock_get_doc.assert_called_once()
            mock_add.assert_called_once_with(skill)
            assert "Full SOP document" in result

    @pytest.mark.asyncio
    async def test_reload_returns_summary(self) -> None:
        skill = _make_mcp_skill(name="mcp_search_skill", tools=["search_api"])
        backend = AsyncMock()

        with (
            patch(
                "myrm_agent_harness.agent._skill_agent_context.get_loaded_skills",
                return_value=[skill],
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.skills.select.skill_select_tool.get_skill_document",
            ) as mock_get_doc,
        ):
            tool = create_select_skill_tool([skill], backend)
            result = await tool.ainvoke(
                {"skill_names": ["mcp_search_skill"], "reason": "testing"}
            )

            mock_get_doc.assert_not_called()
            assert "already loaded" in result
            assert "search_api" in result

    @pytest.mark.asyncio
    async def test_nonexistent_skill_returns_error(self) -> None:
        skill = _make_mcp_skill(name="existing_skill")
        backend = AsyncMock()

        with patch(
            "myrm_agent_harness.agent._skill_agent_context.get_loaded_skills",
            return_value=[],
        ):
            tool = create_select_skill_tool([skill], backend)
            result = await tool.ainvoke(
                {"skill_names": ["nonexistent_skill"], "reason": "testing"}
            )

            assert "not found" in result

    @pytest.mark.asyncio
    async def test_mixed_first_load_and_reload(self) -> None:
        skill_a = _make_mcp_skill(name="skill_a", tools=["tool_a"])
        skill_b = _make_mcp_skill(name="skill_b", tools=["tool_b"])
        backend = AsyncMock()

        with (
            patch(
                "myrm_agent_harness.agent._skill_agent_context.get_loaded_skills",
                return_value=[skill_a],
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.skills.select.skill_select_tool.get_skill_document",
                return_value="# skill_b Full SOP",
            ),
            patch(
                "myrm_agent_harness.agent._skill_agent_context.add_loaded_skill",
            ),
        ):
            tool = create_select_skill_tool([skill_a, skill_b], backend)
            result = await tool.ainvoke(
                {"skill_names": ["skill_a", "skill_b"], "reason": "testing"}
            )

            assert "already loaded" in result
            assert "skill_b Full SOP" in result


class TestCleanupSessionContextFilesEdgeCases:
    """Additional edge case tests for cleanup_session_context_files."""

    @pytest.mark.asyncio
    async def test_context_root_exists_but_session_dir_missing(self) -> None:
        """When CONTEXT_ROOT exists but the session directory doesn't, should skip."""
        from typing import cast

        from myrm_agent_harness.runtime.context.offload import (
            cleanup_session_context_files,
        )

        @dataclass
        class StubExecutor:
            workspace_path: str = "/tmp/workspace"
            executed: list[object] = field(default_factory=list)

            async def execute_bash(self, context: object) -> None:
                self.executed.append(context)

        executor = StubExecutor()

        def selective_isdir(path: str) -> bool:
            from myrm_agent_harness.runtime.execution_paths import CONTEXT_ROOT

            return path == CONTEXT_ROOT

        with patch(
            "myrm_agent_harness.runtime.context.cleanup_ops.os.path.isdir",
            side_effect=selective_isdir,
        ):
            await cleanup_session_context_files("test_chat_123", cast("CodeExecutor", executor))

        assert len(executor.executed) == 0

    @pytest.mark.asyncio
    async def test_none_chat_id_skips(self) -> None:
        """When chat_id is None (falsy), should skip cleanly."""
        from typing import cast

        from myrm_agent_harness.runtime.context.offload import (
            cleanup_session_context_files,
        )

        @dataclass
        class StubExecutor:
            workspace_path: str = "/tmp/workspace"
            executed: list[object] = field(default_factory=list)

            async def execute_bash(self, context: object) -> None:
                self.executed.append(context)

        executor = StubExecutor()

        await cleanup_session_context_files("", cast("CodeExecutor", executor))

        assert len(executor.executed) == 0
