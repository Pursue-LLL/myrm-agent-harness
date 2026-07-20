"""Tests for readonly mode security isolation in delegate_task.

Covers:
- disallowed_tools blocklist enforcement when readonly=True
- system_prompt READONLY MODE hint injection
- Interaction with existing disallowed_tools (merge, not overwrite)
- Interaction with tools allowlist (both empty and non-empty)
- filter_tools integration: readonly-blocked tools are actually filtered out
"""

from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.sub_agents.types import (
    SubagentConfig,
)

READONLY_BLOCKED_TOOLS = frozenset(
    {"write_file", "execute_terminal_command", "bash_run_command", "git_commit"}
)
READONLY_HINT = "[READONLY MODE]"


def _apply_readonly(config: SubagentConfig) -> SubagentConfig:
    """Replicate the readonly logic from delegate_task_tool.py."""
    readonly_blocked = frozenset(
        {"write_file", "execute_terminal_command", "bash_run_command", "git_commit"}
    )
    readonly_hint = (
        "\n\n[READONLY MODE] You are in read-only mode. "
        "You can only read and analyze \u2014 do NOT attempt file writes, "
        "terminal commands, or git commits."
    )
    return replace(
        config,
        disallowed_tools=config.disallowed_tools | readonly_blocked,
        system_prompt=config.system_prompt + readonly_hint,
    )


class TestReadonlyDisallowedTools:
    """Verify disallowed_tools blocklist is correctly set when readonly=True."""

    def test_empty_default_config(self):
        """When config has no existing restrictions, all 4 write tools are blocked."""
        config = SubagentConfig(system_prompt="test")
        assert config.tools == ()
        assert config.disallowed_tools == frozenset()

        new = _apply_readonly(config)
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
            tools=("write_file", "web_search_tool", "memory_search_tool"),
        )
        new = _apply_readonly(config)
        assert "write_file" in new.disallowed_tools
        assert new.tools == ("write_file", "web_search_tool", "memory_search_tool")

    def test_idempotent(self):
        """Applying readonly twice produces the same result."""
        config = SubagentConfig(system_prompt="test")
        first = _apply_readonly(config)
        second = _apply_readonly(first)
        assert first.disallowed_tools == second.disallowed_tools


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
            "write_file",
            "web_search_tool",
            "memory_search_tool",
            "bash_run_command",
            "execute_terminal_command",
            "git_commit",
            "read_file",
        ]:
            t = MagicMock()
            t.name = name
            tools.append(t)
        return tools

    def test_readonly_blocks_write_tools(self, mock_tools):
        from myrm_agent_harness.agent.sub_agents.builder import filter_tools

        config = SubagentConfig(system_prompt="test")
        readonly_config = _apply_readonly(config)

        filtered = filter_tools(readonly_config, mock_tools)
        filtered_names = {t.name for t in filtered}

        for blocked in READONLY_BLOCKED_TOOLS:
            assert blocked not in filtered_names, f"{blocked} should be filtered out"

        assert "web_search_tool" in filtered_names
        assert "memory_search_tool" in filtered_names
        assert "read_file" in filtered_names

    def test_readonly_plus_global_blacklist(self, mock_tools):
        """Readonly blocks + global blacklist both applied."""
        from myrm_agent_harness.agent.sub_agents.builder import filter_tools

        delegate_mock = MagicMock()
        delegate_mock.name = "delegate_task_tool"
        all_tools = [*mock_tools, delegate_mock]

        config = SubagentConfig(system_prompt="test")
        readonly_config = _apply_readonly(config)

        filtered = filter_tools(readonly_config, all_tools)
        filtered_names = {t.name for t in filtered}

        assert "delegate_task_tool" not in filtered_names
        assert "write_file" not in filtered_names
        assert "web_search_tool" in filtered_names

    def test_non_readonly_allows_write_tools(self, mock_tools):
        """Without readonly, write tools are NOT blocked (baseline)."""
        from myrm_agent_harness.agent.sub_agents.builder import filter_tools

        config = SubagentConfig(system_prompt="test")
        filtered = filter_tools(config, mock_tools)
        filtered_names = {t.name for t in filtered}

        assert "write_file" in filtered_names
        assert "bash_run_command" in filtered_names


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
        assert "write_file" in new.disallowed_tools
