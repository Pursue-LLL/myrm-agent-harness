"""Tests for StableDeferredIndex prompt section."""

from __future__ import annotations

from myrm_agent_harness.agent.tool_management.defer.stable_index import (
    DEFERRED_TOOLS_MARKER,
    build_deferred_tools_prompt_section,
)


def test_stable_index_empty() -> None:
    assert build_deferred_tools_prompt_section([]) == ""


def test_stable_index_sorted_names() -> None:
    section = build_deferred_tools_prompt_section(["cron_manage_tool", "bash_process_tool"])
    assert DEFERRED_TOOLS_MARKER in section
    assert "bash_process_tool\ncron_manage_tool" in section
    assert "invoke_deferred_tool" in section
