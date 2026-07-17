"""Tests that skill_discovery_tool is Turn1 eager when discovery_backend is provided."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools import get_meta_tools
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry


@pytest.fixture
def discovery_backend() -> MagicMock:
    backend = MagicMock()
    backend.install_from_url = MagicMock()
    backend.uninstall = MagicMock()
    return backend


@pytest.fixture
def skill_backend() -> MagicMock:
    return MagicMock()


class TestSkillDiscoveryEager:
    def test_skill_discovery_in_resolved_tools(
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

        returned_names = {t.name for t in tools}
        assert "skill_discovery_tool" in returned_names

    def test_skill_discovery_not_in_discoverable_registry(
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

        discoverable_names = {t.name for t in registry.get_discoverable_tools()}
        assert "skill_discovery_tool" not in discoverable_names
