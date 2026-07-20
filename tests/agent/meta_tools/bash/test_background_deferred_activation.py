"""Tests for session-scoped deferred tool activation."""

from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.meta_tools.bash._background_registry import (
    BackgroundProcessRegistry,
)
from myrm_agent_harness.agent.meta_tools.bash.session_spawn_lifecycle import (
    activate_session_deferred_tool,
    clear_session_deferred_tools,
    get_session_deferred_tool_names,
    reset_deferred_activation_for_tests,
)
from myrm_agent_harness.toolkits.code_execution.executors.models import (
    AsyncProcessProtocol,
)

from tests.agent.meta_tools.bash.test_background_registry import _FakeProc


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


def test_activate_ignores_empty_session_or_tool() -> None:
    activate_session_deferred_tool("", "bash_process_tool")
    activate_session_deferred_tool("chat-1", "")
    assert get_session_deferred_tool_names("chat-1") == frozenset()


def test_get_and_clear_ignore_empty_session_id() -> None:
    assert get_session_deferred_tool_names("") == frozenset()
    clear_session_deferred_tools("")
    activate_session_deferred_tool("chat-1", "bash_process_tool")
    clear_session_deferred_tools("")
    assert get_session_deferred_tool_names("chat-1") == frozenset({"bash_process_tool"})


@pytest.mark.asyncio
async def test_registry_clears_deferred_when_last_shell_job_exits() -> None:
    reset_deferred_activation_for_tests()
    registry = BackgroundProcessRegistry(reap_delay_seconds=0)
    activate_session_deferred_tool("chat-shell", "bash_process_tool")

    proc = _FakeProc(pid=4242, stdout=[b"done\n"], stderr=[])
    await registry.register(
        cast(AsyncProcessProtocol, proc),
        command="echo done",
        session_id="chat-shell",
        finish_listener=AsyncMock(),
    )
    proc.finish(0)
    await asyncio.sleep(0.08)

    assert get_session_deferred_tool_names("chat-shell") == frozenset()


@pytest.mark.asyncio
async def test_registry_keeps_deferred_while_sibling_shell_job_running() -> None:
    reset_deferred_activation_for_tests()
    registry = BackgroundProcessRegistry(reap_delay_seconds=300)
    activate_session_deferred_tool("chat-shell", "bash_process_tool")

    slow = _FakeProc(pid=5001, stdout=[], stderr=[])
    fast = _FakeProc(pid=5002, stdout=[b"ok\n"], stderr=[])
    await registry.register(
        cast(AsyncProcessProtocol, slow),
        command="sleep 999",
        session_id="chat-shell",
    )
    await registry.register(
        cast(AsyncProcessProtocol, fast),
        command="echo ok",
        session_id="chat-shell",
    )
    fast.finish(0)
    await asyncio.sleep(0.08)

    assert get_session_deferred_tool_names("chat-shell") == frozenset({"bash_process_tool"})
    slow.finish(0)
    await asyncio.sleep(0.08)
    assert get_session_deferred_tool_names("chat-shell") == frozenset()
