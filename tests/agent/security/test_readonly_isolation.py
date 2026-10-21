"""Tests for readonly mode security isolation in delegate_task.

Covers:
- disallowed_tools blocklist enforcement when readonly=True
- system_prompt READONLY MODE hint injection
- Interaction with existing disallowed_tools (merge, not overwrite)
- Interaction with tools allowlist (both empty and non-empty)
- filter_tools integration: readonly-blocked tools are actually filtered out
"""

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.sub_agents.builder import filter_tools
from myrm_agent_harness.agent.sub_agents.spawn_prep import apply_readonly_to_config
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, WorkspacePolicy

READONLY_BLOCKED_TOOLS = frozenset({"file_write_tool", "file_edit_tool", "bash_code_execute_tool"})
READONLY_HINT = "[READONLY MODE]"


def _apply_readonly(config: SubagentConfig) -> SubagentConfig:
    return apply_readonly_to_config(config, readonly=True)


class TestReadonlyDisallowedTools:
    """Verify disallowed_tools blocklist is correctly set when readonly=True."""

    def test_empty_default_config(self):
        """When config has no existing restrictions, every native workspace mutator is blocked."""
        config = SubagentConfig(system_prompt="test")
        assert config.tools == ()
        assert config.disallowed_tools == frozenset()

        new = _apply_readonly(config)
        assert new.workspace_policy == WorkspacePolicy.READ_ONLY_SANDBOX
        for tool in READONLY_BLOCKED_TOOLS:
            assert tool in new.disallowed_tools, f"{tool} should be blocked"

    def test_preserves_existing_disallowed_tools(self):
        """Existing disallowed_tools are preserved when adding readonly blocks."""
        config = SubagentConfig(
            system_prompt="test",
            disallowed_tools=frozenset({"custom_danger_tool", "another_tool"}),
        )
        new = _apply_readonly(config)
        assert "custom_danger_tool" in new.disallowed_tools
        assert "another_tool" in new.disallowed_tools
        for tool in READONLY_BLOCKED_TOOLS:
            assert tool in new.disallowed_tools

    def test_with_explicit_allowlist(self):
        """readonly blocks are added even when tools allowlist is set."""
        config = SubagentConfig(
            system_prompt="test",
            tools=("file_write_tool", "web_search_tool", "memory_search_tool"),
        )
        new = _apply_readonly(config)
        assert "file_write_tool" in new.disallowed_tools
        assert new.tools == ("file_write_tool", "web_search_tool", "memory_search_tool")

    def test_idempotent(self):
        """Applying readonly twice produces the same result."""
        config = SubagentConfig(system_prompt="test")
        first = _apply_readonly(config)
        second = _apply_readonly(first)
        assert first.disallowed_tools == second.disallowed_tools

    def test_not_readonly_returns_config_unchanged(self):
        config = SubagentConfig(system_prompt="test")
        assert apply_readonly_to_config(config, readonly=False) is config


class TestReadonlySystemPrompt:
    """Verify system_prompt READONLY MODE hint injection."""

    def test_hint_appended(self):
        """READONLY MODE hint is appended to system_prompt."""
        config = SubagentConfig(system_prompt="You are a research assistant.")
        new = _apply_readonly(config)
        assert READONLY_HINT in new.system_prompt
        assert new.system_prompt.startswith("You are a research assistant.")

    def test_original_prompt_preserved(self):
        """Original system_prompt content is not modified."""
        original = "Complex prompt with\nmultiple lines\nand special chars: !@#$%"
        config = SubagentConfig(system_prompt=original)
        new = _apply_readonly(config)
        assert new.system_prompt.startswith(original)
        assert READONLY_HINT in new.system_prompt

    def test_empty_prompt(self):
        """Works even with empty system_prompt."""
        config = SubagentConfig(system_prompt="")
        new = _apply_readonly(config)
        assert READONLY_HINT in new.system_prompt


class TestFilterToolsIntegration:
    """Verify filter_tools correctly blocks readonly tools via disallowed_tools."""

    @pytest.fixture
    def mock_tools(self):
        tools = []
        for name in [
            "file_write_tool",
            "file_edit_tool",
            "bash_code_execute_tool",
            "web_search_tool",
            "memory_search_tool",
            "file_read_tool",
        ]:
            t = MagicMock()
            t.name = name
            tools.append(t)
        return tools

    def test_readonly_blocks_write_tools(self, mock_tools):
        config = SubagentConfig(system_prompt="test")
        readonly_config = _apply_readonly(config)

        filtered = filter_tools(readonly_config, mock_tools)
        filtered_names = {t.name for t in filtered}

        for blocked in READONLY_BLOCKED_TOOLS:
            assert blocked not in filtered_names, f"{blocked} should be filtered out"

        assert "web_search_tool" in filtered_names
        assert "memory_search_tool" in filtered_names
        assert "file_read_tool" in filtered_names

    def test_readonly_plus_global_blacklist(self, mock_tools):
        """Readonly blocks + global blacklist both applied."""
        delegate_mock = MagicMock()
        delegate_mock.name = "delegate_task_tool"
        all_tools = [*mock_tools, delegate_mock]

        config = SubagentConfig(system_prompt="test")
        readonly_config = _apply_readonly(config)

        filtered = filter_tools(readonly_config, all_tools)
        filtered_names = {t.name for t in filtered}

        assert "delegate_task_tool" not in filtered_names
        assert "file_write_tool" not in filtered_names
        assert "web_search_tool" in filtered_names

    def test_non_readonly_allows_write_tools(self, mock_tools):
        """Without readonly, write tools are NOT blocked (baseline)."""
        config = SubagentConfig(system_prompt="test")
        filtered = filter_tools(config, mock_tools)
        filtered_names = {t.name for t in filtered}

        assert "file_write_tool" in filtered_names
        assert "bash_code_execute_tool" in filtered_names


class TestReadonlyNoSideEffects:
    """Verify readonly does not mutate original config."""

    def test_original_config_unchanged(self):
        config = SubagentConfig(
            system_prompt="original",
            disallowed_tools=frozenset({"existing_block"}),
        )
        new = _apply_readonly(config)

        assert config.system_prompt == "original"
        assert config.disallowed_tools == frozenset({"existing_block"})
        assert READONLY_HINT in new.system_prompt
        assert "file_write_tool" in new.disallowed_tools
