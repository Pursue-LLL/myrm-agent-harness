"""Unit tests for Background Shell Runtime v2.1 harness changes."""

from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.meta_tools.bash._background_registry import (
    BackgroundProcessRegistry,
    get_background_registry,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_auto_yield import (
    DEFAULT_YIELD_AFTER_SECONDS,
    build_auto_yield_return,
    resolve_yield_seconds,
    should_auto_yield,
    wait_for_yield_window,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_process_tools import create_bash_process_tool
from myrm_agent_harness.agent.meta_tools.bash._background_types import BackgroundProcessInfo
from myrm_agent_harness.toolkits.code_execution.executors.models import AsyncProcessProtocol

from tests.agent.meta_tools.bash.test_background_registry import _FakeProc


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    from myrm_agent_harness.agent.meta_tools.bash._background_registry import get_background_registry
    from myrm_agent_harness.agent.meta_tools.bash.session_spawn_lifecycle import reset_deferred_activation_for_tests

    registry = get_background_registry()
    registry._entries.clear()  # type: ignore[attr-defined]
    reset_deferred_activation_for_tests()
    yield
    registry._entries.clear()  # type: ignore[attr-defined]
    reset_deferred_activation_for_tests()


@pytest.mark.asyncio
async def test_registry_redacts_sensitive_output_at_write_time() -> None:
    registry = BackgroundProcessRegistry()
    secret_line = b"Authorization: Bearer sk-live-abcdefghijklmnopqrstuvwxyz\n"
    proc = _FakeProc(pid=9001, stdout=[secret_line], stderr=[])
    await registry.register(cast(AsyncProcessProtocol, proc), command="echo leak", session_id="s-redact")
    proc.finish(0)
    await asyncio.sleep(0.05)

    streams = registry.get_output(9001, max_lines=10)
    joined = " ".join(str(line) for line in streams["stdout"])
    assert "sk-live-abcdefghijklmnopqrstuvwxyz" not in joined


@pytest.mark.asyncio
async def test_registry_wait_respects_cap_and_still_running() -> None:
    registry = BackgroundProcessRegistry()
    proc = _FakeProc(pid=9002, stdout=[], stderr=[])
    await registry.register(cast(AsyncProcessProtocol, proc), command="sleep 999", session_id="s-wait")

    result = await registry.wait_for_process(9002, timeout_seconds=0.2)
    assert result["still_running"] is True
    assert result["status"] == "running"

    capped = await registry.wait_for_process(9002, timeout_seconds=999)
    assert capped["still_running"] is True


@pytest.mark.asyncio
async def test_registry_poll_hint_backoff_on_empty_polls() -> None:
    registry = BackgroundProcessRegistry()
    proc = _FakeProc(pid=9003, stdout=[b"once\n"], stderr=[])
    await registry.register(cast(AsyncProcessProtocol, proc), command="echo once", session_id="s-poll")
    await asyncio.sleep(0.05)

    first = registry.get_output(9003, since_cursor=None)
    cursor = int(first["next_cursor"])
    second = registry.get_output(9003, since_cursor=cursor)
    hint = second["poll_hint"]
    assert isinstance(hint, dict)
    assert hint["has_new_output"] is False
    assert hint["suggested_wait_ms"] >= 5000

    third = registry.get_output(9003, since_cursor=cursor)
    assert third["poll_hint"]["suggested_wait_ms"] >= hint["suggested_wait_ms"]


@pytest.mark.asyncio
async def test_count_running_scoped_by_session() -> None:
    registry = BackgroundProcessRegistry()
    registry._entries.clear()  # type: ignore[attr-defined]

    await registry.register(
        cast(AsyncProcessProtocol, _FakeProc(pid=1, stdout=[], stderr=[])),
        command="a",
        session_id="chat-a",
    )
    await registry.register(
        cast(AsyncProcessProtocol, _FakeProc(pid=2, stdout=[], stderr=[])),
        command="b",
        session_id="chat-b",
    )
    assert registry.count_running() == 2
    assert registry.count_running("chat-a") == 1


def test_auto_yield_whitelist_and_defaults() -> None:
    assert should_auto_yield(command="npm test", run_in_background=False, yield_after_seconds=None)
    assert not should_auto_yield(command="echo hi", run_in_background=False, yield_after_seconds=None)
    assert resolve_yield_seconds(None) == DEFAULT_YIELD_AFTER_SECONDS
    assert resolve_yield_seconds(0) is None


def test_build_auto_yield_return_still_running() -> None:
    info = BackgroundProcessInfo(
        job_id="chat-yield",
        pid=55,
        command="npm run build",
        session_id="chat-yield",
        started_at=0.0,
        status="running",
    )
    payload = build_auto_yield_return(info=info, yield_seconds=10, registry=BackgroundProcessRegistry())
    assert payload["metadata"]["auto_yielded"] is True
    assert "still running" in str(payload["content"]).lower() or "detached" in str(payload["content"]).lower()


@pytest.mark.asyncio
async def test_bash_process_wait_action_requires_session() -> None:
    tool = create_bash_process_tool()
    result = await tool.ainvoke({"action": "wait", "pid": 1, "timeout_seconds": 1}, config={})
    assert result["metadata"]["error"] == "missing_session_id"


@pytest.mark.asyncio
async def test_bash_process_wait_action_on_finished_job() -> None:
    registry = get_background_registry()
    proc = _FakeProc(pid=9010, stdout=[b"done\n"], stderr=[])
    await registry.register(cast(AsyncProcessProtocol, proc), command="echo done", session_id="chat-wait")
    proc.finish(0)
    await asyncio.sleep(0.15)

    tool = create_bash_process_tool()
    config = {"configurable": {"context": {"session_id": "chat-wait"}}}
    result = await tool.ainvoke({"action": "wait", "pid": 9010, "timeout_seconds": 5}, config=config)
    assert result["metadata"]["still_running"] is False
    assert result["content"]["exit_code"] == 0


def test_hooks_count_running_background_shell_jobs() -> None:
    from myrm_agent_harness.api.hooks import count_running_background_shell_jobs

    registry = BackgroundProcessRegistry()
    with patch(
        "myrm_agent_harness.api.hooks.get_background_registry",
        return_value=registry,
    ):
        registry._entries.clear()  # type: ignore[attr-defined]
        assert count_running_background_shell_jobs() == 0


def test_should_auto_yield_skips_background_spawn() -> None:
    assert not should_auto_yield(command="npm test", run_in_background=True, yield_after_seconds=None)


def test_resolve_yield_seconds_custom_value() -> None:
    assert resolve_yield_seconds(5) == 5


@pytest.mark.asyncio
async def test_wait_for_yield_window_returns_when_job_exits() -> None:
    registry = BackgroundProcessRegistry()
    proc = _FakeProc(pid=9020, stdout=[b"done\n"], stderr=[])
    await registry.register(cast(AsyncProcessProtocol, proc), command="echo done", session_id="s-yield-exit")
    proc.finish(0)
    await asyncio.sleep(0.05)

    info = await wait_for_yield_window(registry, 9020, yield_seconds=10)
    assert info is not None
    assert info.status == "exited"


@pytest.mark.asyncio
async def test_wait_for_yield_window_unknown_pid() -> None:
    registry = BackgroundProcessRegistry()
    info = await wait_for_yield_window(registry, 99999, yield_seconds=1)
    assert info is None


@pytest.mark.asyncio
async def test_build_auto_yield_return_completed_in_window() -> None:
    registry = BackgroundProcessRegistry()
    proc = _FakeProc(pid=9021, stdout=[b"build ok\n"], stderr=[b"warn\n"])
    await registry.register(cast(AsyncProcessProtocol, proc), command="npm run build", session_id="s-yield-done")
    proc.finish(0)
    await asyncio.sleep(0.05)
    info = registry.get(9021)
    assert info is not None

    payload = build_auto_yield_return(info=info, yield_seconds=10, registry=registry)
    assert payload["metadata"]["completed_in_yield_window"] is True
    assert payload["metadata"]["exit_code"] == 0
    assert "build ok" in str(payload["content"])


@pytest.mark.asyncio
async def test_build_auto_yield_return_includes_partial_output() -> None:
    registry = BackgroundProcessRegistry()
    proc = _FakeProc(pid=9022, stdout=[b"partial\n"], stderr=[b"err\n"])
    await registry.register(cast(AsyncProcessProtocol, proc), command="npm test", session_id="s-yield-partial")
    await asyncio.sleep(0.05)

    info = registry.get(9022)
    assert info is not None
    payload = build_auto_yield_return(info=info, yield_seconds=10, registry=registry)
    assert payload["metadata"]["background"] is True
    assert "partial" in str(payload["content"])
    assert "poll_hint" in payload["metadata"]


@pytest.mark.asyncio
async def test_wait_for_yield_window_returns_at_deadline() -> None:
    registry = BackgroundProcessRegistry()
    proc = _FakeProc(pid=9024, stdout=[], stderr=[])
    await registry.register(cast(AsyncProcessProtocol, proc), command="sleep 999", session_id="s-yield-deadline")

    info = await wait_for_yield_window(registry, 9024, yield_seconds=0)
    assert info is not None
    assert info.status == "running"


@pytest.mark.asyncio
async def test_registry_wait_returns_exit_metadata() -> None:
    registry = BackgroundProcessRegistry()
    proc = _FakeProc(pid=9023, stdout=[b"ok\n"], stderr=[])
    await registry.register(cast(AsyncProcessProtocol, proc), command="echo ok", session_id="s-wait-exit")
    proc.finish(2)
    await asyncio.sleep(0.05)

    result = await registry.wait_for_process(9023, timeout_seconds=5.0)
    assert result["still_running"] is False
    assert result["exit_code"] == 2


@pytest.mark.asyncio
async def test_registry_wait_unknown_pid() -> None:
    registry = BackgroundProcessRegistry()
    result = await registry.wait_for_process(99999, timeout_seconds=0.5)
    assert result["found"] is False
    assert result["still_running"] is False


@pytest.mark.asyncio
async def test_bash_process_list_action() -> None:
    registry = get_background_registry()
    proc = _FakeProc(pid=9030, stdout=[], stderr=[])
    await registry.register(cast(AsyncProcessProtocol, proc), command="sleep 1", session_id="chat-list")

    tool = create_bash_process_tool()
    config = {"configurable": {"context": {"session_id": "chat-list"}}}
    result = await tool.ainvoke({"action": "list"}, config=config)
    assert result["content"]["count"] == 1
    assert result["content"]["processes"][0]["pid"] == 9030


@pytest.mark.asyncio
async def test_bash_process_output_success_and_poll_hint() -> None:
    registry = get_background_registry()
    proc = _FakeProc(pid=9031, stdout=[b"line\n"], stderr=[])
    await registry.register(cast(AsyncProcessProtocol, proc), command="echo line", session_id="chat-out")
    await asyncio.sleep(0.05)

    tool = create_bash_process_tool()
    config = {"configurable": {"context": {"session_id": "chat-out"}}}
    result = await tool.ainvoke({"action": "output", "pid": 9031}, config=config)
    assert result["content"]["stdout"]
    assert "poll_hint" in result["metadata"]


@pytest.mark.asyncio
async def test_bash_process_output_wrong_session() -> None:
    registry = get_background_registry()
    proc = _FakeProc(pid=9032, stdout=[], stderr=[])
    await registry.register(cast(AsyncProcessProtocol, proc), command="sleep", session_id="owner")

    tool = create_bash_process_tool()
    config = {"configurable": {"context": {"session_id": "other"}}}
    result = await tool.ainvoke({"action": "output", "pid": 9032}, config=config)
    assert result["metadata"]["found"] is False


@pytest.mark.asyncio
async def test_bash_process_wait_still_running_message() -> None:
    registry = get_background_registry()
    proc = _FakeProc(pid=9033, stdout=[], stderr=[])
    await registry.register(cast(AsyncProcessProtocol, proc), command="sleep 999", session_id="chat-wait-run")

    tool = create_bash_process_tool()
    config = {"configurable": {"context": {"session_id": "chat-wait-run"}}}
    result = await tool.ainvoke({"action": "wait", "pid": 9033, "timeout_seconds": 1}, config=config)
    assert result["metadata"]["still_running"] is True
    assert "still running" in str(result["content"]["message"]).lower()


@pytest.mark.asyncio
async def test_bash_process_kill_success() -> None:
    registry = get_background_registry()
    proc = _FakeProc(pid=9034, stdout=[], stderr=[])
    await registry.register(cast(AsyncProcessProtocol, proc), command="sleep 999", session_id="chat-kill")

    tool = create_bash_process_tool()
    config = {"configurable": {"context": {"session_id": "chat-kill"}}}
    with patch(
        "myrm_agent_harness.agent.meta_tools.bash._background_registry.kill_process_group",
    ) as mock_kill:
        result = await tool.ainvoke({"action": "kill", "pid": 9034, "force": True}, config=config)
        mock_kill.assert_called()
    assert result["metadata"]["killed"] is True


@pytest.mark.asyncio
async def test_bash_process_kill_wrong_session() -> None:
    registry = get_background_registry()
    proc = _FakeProc(pid=9035, stdout=[], stderr=[])
    await registry.register(cast(AsyncProcessProtocol, proc), command="sleep", session_id="owner-kill")

    tool = create_bash_process_tool()
    config = {"configurable": {"context": {"session_id": "other-kill"}}}
    result = await tool.ainvoke({"action": "kill", "pid": 9035}, config=config)
    assert result["metadata"]["found"] is False


@pytest.mark.asyncio
async def test_bash_process_missing_pid_errors() -> None:
    tool = create_bash_process_tool()
    config = {"configurable": {"context": {"session_id": "chat-missing-pid"}}}
    result = await tool.ainvoke({"action": "output"}, config=config)
    assert result["metadata"]["error"] == "missing_pid"
