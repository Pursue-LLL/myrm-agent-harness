"""Tests that skill_market_tool is NOT created by get_meta_tools (server/user_tools SSOT)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools import get_meta_tools
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
            enable_file_tools=False,
            enable_shell_tools=False,
            enable_answer_tool=False,
        )

        returned_names = {t.name for t in tools}
        assert "skill_market_tool" not in returned_names
        assert "skill_manage_tool" not in returned_names

    def test_has_manage_tool_injects_evolution_rules_without_manage_factory(
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
        tools = get_meta_tools(
            skills,
            skill_backend,
            registry=registry,
            has_manage_tool=True,
            enable_file_tools=False,
            enable_shell_tools=False,
            enable_answer_tool=False,
        )
        select_tool = next(t for t in tools if t.name == "skill_select_tool")
        assert "skill_manage_tool" in select_tool.description
