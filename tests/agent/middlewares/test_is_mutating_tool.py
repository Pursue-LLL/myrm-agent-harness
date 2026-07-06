"""Tests for is_mutating_tool SSOT used by Cron post-run verification."""

from myrm_agent_harness.agent.middlewares.completion_guard import is_mutating_tool


def test_is_mutating_tool_detects_file_write_alias() -> None:
    assert is_mutating_tool("file_write_tool") is True


def test_is_mutating_tool_detects_bash_alias() -> None:
    assert is_mutating_tool("bash_code_execute_tool") is True


def test_is_mutating_tool_detects_browser_alias() -> None:
    assert is_mutating_tool("browser_navigate_tool") is True


def test_is_mutating_tool_detects_cron_manage_alias() -> None:
    assert is_mutating_tool("cron_manage_tool") is True


def test_is_mutating_tool_ignores_read_only_tools() -> None:
    assert is_mutating_tool("grep_tool") is False
    assert is_mutating_tool("file_read_tool") is False


def test_is_mutating_tool_ignores_retired_canvas_tool() -> None:
    assert is_mutating_tool("canvas_tool") is False
