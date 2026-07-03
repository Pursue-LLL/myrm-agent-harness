"""Tests for session-scoped deferred tool activation."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.bash.background_deferred_activation import (
    activate_session_deferred_tool,
    clear_session_deferred_tools,
    get_session_deferred_tool_names,
    reset_deferred_activation_for_tests,
)
from myrm_agent_harness.agent.middlewares.deferred_tool_middleware import (
    collect_activated_native_tool_names,
)


def setup_function() -> None:
    reset_deferred_activation_for_tests()


def test_activate_and_read_session_tools() -> None:
    activate_session_deferred_tool("chat-1", "bash_process_tool")
    assert get_session_deferred_tool_names("chat-1") == frozenset({"bash_process_tool"})
    assert get_session_deferred_tool_names("chat-2") == frozenset()


def test_clear_session_tools() -> None:
    activate_session_deferred_tool("chat-1", "bash_process_tool")
    clear_session_deferred_tools("chat-1")
    assert get_session_deferred_tool_names("chat-1") == frozenset()


def test_collect_activated_includes_session_spawn() -> None:
    activate_session_deferred_tool("chat-9", "bash_process_tool")
    names = collect_activated_native_tool_names([], session_id="chat-9")
    assert "bash_process_tool" in names
