"""Tests that skill_market_tool is NOT created by get_meta_tools (server/user_tools SSOT)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools import get_meta_tools
from myrm_agent_harness.agent.meta_tools.mount_policy import FileAccessMode
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry


@pytest.fixture
def skill_backend() -> MagicMock:
    return MagicMock()


class TestSkillMarketNotInGetMetaTools:
    def test_skill_market_not_returned_by_get_meta_tools(
        self,
        skill_backend: MagicMock,
    ) -> None:
        registry = ToolRegistry()
        tools = get_meta_tools(
            [],
            skill_backend,
            registry=registry,
            file_access_mode=FileAccessMode.NONE,
            enable_shell_tools=False,
            enable_answer_tool=False,
        )

        returned_names = {t.name for t in tools}
        assert "skill_market_tool" not in returned_names
        assert "skill_manage_tool" not in returned_names

    def test_skill_select_description_is_byte_identical_regardless_of_manage_tool(
        self,
        skill_backend: MagicMock,
    ) -> None:
        from myrm_agent_harness.backends.skills.types import SkillMetadata

        skills = [
            SkillMetadata(
                name="demo_skill",
                description="Demo",
                model_invocable=True,
                available=True,
            )
        ]
        registry = ToolRegistry()
        without_manage = get_meta_tools(
            skills,
            skill_backend,
            registry=registry,
            has_manage_tool=False,
            file_access_mode=FileAccessMode.NONE,
            enable_shell_tools=False,
            enable_answer_tool=False,
        )
        with_manage = get_meta_tools(
            skills,
            skill_backend,
            registry=registry,
            has_manage_tool=True,
            file_access_mode=FileAccessMode.NONE,
            enable_shell_tools=False,
            enable_answer_tool=False,
        )
        select_without = next(t for t in without_manage if t.name == "skill_select_tool")
        select_with = next(t for t in with_manage if t.name == "skill_select_tool")
        assert select_without.description == select_with.description
        assert "skill_manage_tool" not in (select_without.description or "")
