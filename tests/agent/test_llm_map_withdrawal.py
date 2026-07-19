"""Contract tests: llm_map primitive fully withdrawn from harness."""

from __future__ import annotations

import inspect

import pytest

from myrm_agent_harness.agent._skill_agent_tools import SkillAgentToolsMixin
from myrm_agent_harness.agent.skill_agent import SkillAgent
from myrm_agent_harness.agent.tool_management.tool_layers import _TOOL_LAYERS


class TestLlmMapWithdrawalHarness:
    def test_llm_map_tool_not_in_tool_layers(self) -> None:
        assert "llm_map_tool" not in _TOOL_LAYERS

    def test_delegation_v2_tools_registered(self) -> None:
        assert "delegate_task_tool" in _TOOL_LAYERS
        assert "subagent_control_tool" in _TOOL_LAYERS
        assert "batch_delegate_tasks_tool" not in _TOOL_LAYERS

    def test_create_skill_agent_has_no_enable_llm_map_param(self) -> None:
        from myrm_agent_harness.agent._factory.builder import create_skill_agent

        assert "enable_llm_map" not in inspect.signature(create_skill_agent).parameters

    def test_skill_agent_init_has_no_enable_llm_map_param(self) -> None:
        assert "enable_llm_map" not in inspect.signature(SkillAgent.__init__).parameters

    def test_get_meta_tools_has_no_enable_llm_map_param(self) -> None:
        from myrm_agent_harness.agent.meta_tools import get_meta_tools

        assert "enable_llm_map" not in inspect.signature(get_meta_tools).parameters

    def test_skill_agent_tools_mixin_has_no_llm_map_factory(self) -> None:
        assert not hasattr(SkillAgentToolsMixin, "_create_llm_map_tool")
