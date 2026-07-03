"""Tests that skill_discovery_tool is deferred via ToolRegistry in get_meta_tools."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools import get_meta_tools
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.backends.skills.types import SkillMetadata


@pytest.fixture
def discovery_backend() -> MagicMock:
    backend = MagicMock()
    backend.install_from_url = MagicMock()
    backend.uninstall = MagicMock()
    return backend


@pytest.fixture
def skill_backend() -> MagicMock:
    return MagicMock()


class TestSkillDiscoveryDeferred:
    def test_skill_discovery_not_in_resolved_tools(
        self,
        discovery_backend: MagicMock,
        skill_backend: MagicMock,
    ) -> None:
        registry = ToolRegistry()
        tools = get_meta_tools(
            [],
            skill_backend,
            registry=registry,
            discovery_backend=discovery_backend,
            enable_file_tools=False,
            enable_bash=False,
            enable_answer_tool=False,
        )

        resolved_names = {t.name for t in registry.resolve()}
        assert "skill_discovery_tool" not in resolved_names

        returned_names = {t.name for t in tools}
        assert "skill_discovery_tool" not in returned_names

    def test_skill_discovery_in_deferred_registry(
        self,
        discovery_backend: MagicMock,
        skill_backend: MagicMock,
    ) -> None:
        registry = ToolRegistry()
        get_meta_tools(
            [],
            skill_backend,
            registry=registry,
            discovery_backend=discovery_backend,
            enable_file_tools=False,
            enable_bash=False,
            enable_answer_tool=False,
        )

        deferred_names = {t.name for t in registry.get_deferred_tools()}
        assert "skill_discovery_tool" in deferred_names
