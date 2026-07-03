"""Tests that skill_analyze_tool stays removed from get_meta_tools and discover."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools import get_meta_tools
from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
    sync_discover_capability_tool,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.backends.skills.types import SkillMetadata
from myrm_agent_harness.core.security.tool_registry import (
    BUILTIN_TOOL_NAMES,
    TOOL_SAFETY_METADATA,
)


@pytest.fixture
def skill_backend() -> MagicMock:
    return MagicMock()


@pytest.fixture
def sample_skill() -> SkillMetadata:
    return SkillMetadata(
        name="demo_skill",
        description="Demo skill for skill_analyze removal tests",
        model_invocable=True,
        available=True,
    )


class TestSkillAnalyzeRemoved:
    def test_skill_analyze_not_registered_when_skills_present(
        self,
        skill_backend: MagicMock,
        sample_skill: SkillMetadata,
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
        returned_names = {t.name for t in tools}
        discoverable_names = {t.name for t in registry.get_discoverable_tools()}

        assert "skill_analyze_tool" not in resolved_names
        assert "skill_analyze_tool" not in returned_names
        assert "skill_analyze_tool" not in discoverable_names

    def test_discover_description_omits_skill_analyze(
        self,
        skill_backend: MagicMock,
        sample_skill: SkillMetadata,
    ) -> None:
        registry = ToolRegistry()
        get_meta_tools(
            [sample_skill],
            skill_backend,
            registry=registry,
            enable_file_tools=True,
            enable_bash=False,
            enable_answer_tool=False,
        )
        sync_discover_capability_tool(registry, skills=[sample_skill])

        discover = next(
            t for t in registry.resolve() if t.name == "discover_capability_tool"
        )
        description = discover.description or ""
        assert "skill_analyze_tool" not in description
        assert "skill_analyze" not in description.lower()

    def test_security_registry_excludes_skill_analyze(self) -> None:
        assert "skill_analyze_tool" not in BUILTIN_TOOL_NAMES
        assert "skill_analyze_tool" not in TOOL_SAFETY_METADATA
