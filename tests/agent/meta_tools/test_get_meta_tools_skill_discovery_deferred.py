"""Tests that skill_market_tool is Turn1 eager when market_backend is provided."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools import get_meta_tools
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry


@pytest.fixture
def market_backend() -> MagicMock:
    backend = MagicMock()
    backend.install_from_url = MagicMock()
    backend.uninstall = MagicMock()
    return backend


@pytest.fixture
def skill_backend() -> MagicMock:
    return MagicMock()


class TestSkillMarketEager:
    def test_skill_market_in_resolved_tools(
        self,
        market_backend: MagicMock,
        skill_backend: MagicMock,
    ) -> None:
        registry = ToolRegistry()
        tools = get_meta_tools(
            [],
            skill_backend,
            registry=registry,
            market_backend=market_backend,
            enable_file_tools=False,
            enable_shell_tools=False,
            enable_answer_tool=False,
        )

        returned_names = {t.name for t in tools}
        assert "skill_market_tool" in returned_names

    def test_skill_market_not_runtime_only(
        self,
        market_backend: MagicMock,
        skill_backend: MagicMock,
    ) -> None:
        registry = ToolRegistry()
        get_meta_tools(
            [],
            skill_backend,
            registry=registry,
            market_backend=market_backend,
            enable_file_tools=False,
            enable_shell_tools=False,
            enable_answer_tool=False,
        )

        runtime_names = {t.name for t in registry.get_runtime_tools()}
        assert "skill_market_tool" not in runtime_names
