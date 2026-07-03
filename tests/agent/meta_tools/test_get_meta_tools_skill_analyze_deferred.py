"""Tests that skill_analyze_tool is deferred via ToolRegistry in get_meta_tools."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.tools import tool

from myrm_agent_harness.agent.meta_tools import get_meta_tools
from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
    sync_discover_capability_tool,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.agent.tool_management.types import ToolBindMode, ToolSource
from myrm_agent_harness.backends.skills.types import SkillMetadata


@pytest.fixture
def sample_skill() -> SkillMetadata:
    return SkillMetadata(
        name="demo_skill",
        description="Demo skill for testing",
        model_invocable=True,
        available=True,
    )


@pytest.fixture
def skill_backend() -> MagicMock:
    backend = MagicMock()
    backend.load_skill = MagicMock()
    return backend


class TestSkillAnalyzeDeferred:
    def test_skill_analyze_not_in_resolved_tools(
        self,
        sample_skill: SkillMetadata,
        skill_backend: MagicMock,
    ) -> None:
        registry = ToolRegistry()
        tools = get_meta_tools(
            [sample_skill],
            skill_backend,
            registry=registry,
            enable_file_tools=False,
            enable_bash=False,
            enable_answer_tool=False,
        )

        resolved_names = {t.name for t in registry.resolve()}
        assert "skill_analyze_tool" not in resolved_names

        returned_names = {t.name for t in tools}
        assert "skill_analyze_tool" not in returned_names
        assert "discover_capability_tool" not in returned_names

        sync_discover_capability_tool(registry, skills=[sample_skill])
        resolved_after_sync = {t.name for t in registry.resolve()}
        assert "discover_capability_tool" in resolved_after_sync

    def test_skill_analyze_in_deferred_registry(
        self,
        sample_skill: SkillMetadata,
        skill_backend: MagicMock,
    ) -> None:
        registry = ToolRegistry()
        get_meta_tools(
            [sample_skill],
            skill_backend,
            registry=registry,
            enable_file_tools=False,
            enable_bash=False,
            enable_answer_tool=False,
        )

        discoverable_names = {t.name for t in registry.get_discoverable_tools()}
        assert "skill_analyze_tool" in discoverable_names

    def test_discover_indexes_deferred_skill_analyze(
        self,
        sample_skill: SkillMetadata,
        skill_backend: MagicMock,
    ) -> None:
        registry = ToolRegistry()
        get_meta_tools(
            [sample_skill],
            skill_backend,
            registry=registry,
            enable_file_tools=False,
            enable_bash=False,
            enable_answer_tool=False,
        )
        sync_discover_capability_tool(registry, skills=[sample_skill])
        discover = next(
            t for t in registry.resolve() if t.name == "discover_capability_tool"
        )
        assert "skill_analyze_tool" in (discover.description or "")

    def test_no_skill_analyze_when_no_skills(
        self,
        skill_backend: MagicMock,
    ) -> None:
        registry = ToolRegistry()

        @tool
        def dummy_deferred() -> str:
            """Deferred placeholder."""
            return "ok"

        registry.register(dummy_deferred, source=ToolSource.META, bind_mode=ToolBindMode.DISCOVERABLE)

        get_meta_tools(
            [],
            skill_backend,
            registry=registry,
            enable_file_tools=False,
            enable_bash=False,
            enable_answer_tool=False,
        )

        discoverable_names = {t.name for t in registry.get_discoverable_tools()}
        assert "skill_analyze_tool" not in discoverable_names


def test_get_meta_tools_requires_tool_registry() -> None:
    with pytest.raises(TypeError, match="ToolRegistry"):
        get_meta_tools([], registry=None)
