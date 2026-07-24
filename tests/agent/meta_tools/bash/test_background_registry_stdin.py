"""Tests for background bash registry stdin writes."""

from __future__ import annotations

import asyncio
from collections import deque
from typing import cast
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools.bash._background_registry import (
    BackgroundProcessRegistry,
    get_background_registry,
)
from myrm_agent_harness.agent.meta_tools.bash._background_registry_stdin import (
    write_background_stdin,
)
from myrm_agent_harness.agent.meta_tools.bash._background_registry_consume import (
    BackgroundRegistryEntry,
)
from myrm_agent_harness.agent.meta_tools.bash._background_types import (
    BackgroundProcessInfo,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_process_tools import (
    create_bash_process_tool,
)
from myrm_agent_harness.toolkits.code_execution.executors.models import (
    AsyncProcessProtocol,
)


class _FakeStdin:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.chunks.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class _ProcWithStdin:
    def __init__(self, pid: int) -> None:
        self._proc = MagicMock()
        self._proc.pid = pid
        self.stdin = _FakeStdin()
        self.stdout = None
        self.stderr = None
        self._exit_event = asyncio.Event()

    async def wait(self) -> int:
        await self._exit_event.wait()
        return 0

    def terminate(self) -> None:
        self._exit_event.set()

    def kill(self) -> None:
        self._exit_event.set()


@pytest.mark.asyncio
async def test_write_background_stdin_submit_appends_newline() -> None:
    proc = _ProcWithStdin(pid=7001)
    info = BackgroundProcessInfo(
        job_id="job-1",
        pid=7001,
        command="npm create vite",
        session_id="sess-1",
        started_at=1.0,
        status="running",
    )
    entry = BackgroundRegistryEntry(
        info=info,
        proc=cast(AsyncProcessProtocol, proc),
        stdout_buffer=deque(),
        stderr_buffer=deque(),
    )

    result = await write_background_stdin(entry, "y", append_newline=True, close=False)
    assert result["ok"] is True
    assert proc.stdin.chunks == [b"y\n"]


@pytest.mark.asyncio
async def test_registry_write_stdin_rejects_unknown_pid() -> None:
    registry = BackgroundProcessRegistry()
    result = await registry.write_stdin(99999, "y")
    assert result["ok"] is False
    assert result["error"] == "not_found"


def test_resolve_permission_type_maps_stdin_to_shell_exec() -> None:
    from myrm_agent_harness.core.security.tool_registry import resolve_permission_type

    assert (
        resolve_permission_type(
            "bash_process_tool", {"action": "submit_stdin", "data": "y"}
        )
        == "shell_exec"
    )
    assert (
        resolve_permission_type("bash_process_tool", {"action": "output", "pid": 1})
        == "bash_process_tool"
    )


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    registry = get_background_registry()
    registry._entries.clear()  # type: ignore[attr-defined]
    yield
    registry._entries.clear()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_write_background_stdin_rejects_not_running() -> None:
    proc = _ProcWithStdin(pid=7002)
    info = BackgroundProcessInfo(
        job_id="job-2",
        pid=7002,
        command="done",
        session_id="sess-2",
        started_at=1.0,
        status="exited",
    )
    entry = BackgroundRegistryEntry(
        info=info,
        proc=cast(AsyncProcessProtocol, proc),
        stdout_buffer=deque(),
        stderr_buffer=deque(),
    )
    result = await write_background_stdin(entry, "y")
    assert result["ok"] is False
    assert result["error"] == "not_running"


@pytest.mark.asyncio
async def test_write_background_stdin_rejects_missing_stdin() -> None:
    proc = _ProcWithStdin(pid=7003)
    proc.stdin = None  # type: ignore[assignment]
    info = BackgroundProcessInfo(
        job_id="job-3",
        pid=7003,
        command="cmd",
        session_id="sess-3",
        started_at=1.0,
        status="running",
    )
    entry = BackgroundRegistryEntry(
        info=info,
        proc=cast(AsyncProcessProtocol, proc),
        stdout_buffer=deque(),
        stderr_buffer=deque(),
    )
    result = await write_background_stdin(entry, "y")
    assert result["ok"] is False
    assert result["error"] == "no_stdin"


@pytest.mark.asyncio
async def test_write_background_stdin_rejects_oversized_payload() -> None:
    proc = _ProcWithStdin(pid=7004)
    info = BackgroundProcessInfo(
        job_id="job-4",
        pid=7004,
        command="cmd",
        session_id="sess-4",
        started_at=1.0,
        status="running",
    )
    entry = BackgroundRegistryEntry(
        info=info,
        proc=cast(AsyncProcessProtocol, proc),
        stdout_buffer=deque(),
        stderr_buffer=deque(),
    )
    result = await write_background_stdin(entry, "x" * (64 * 1024 + 1))
    assert result["ok"] is False
    assert result["error"] == "stdin_too_large"


@pytest.mark.asyncio
async def test_write_background_stdin_close_eof_without_payload() -> None:
    proc = _ProcWithStdin(pid=7005)
    info = BackgroundProcessInfo(
        job_id="job-5",
        pid=7005,
        command="cmd",
        session_id="sess-5",
        started_at=1.0,
        status="running",
    )
    entry = BackgroundRegistryEntry(
        info=info,
        proc=cast(AsyncProcessProtocol, proc),
        stdout_buffer=deque(),
        stderr_buffer=deque(),
    )
    result = await write_background_stdin(entry, "", close=True)
    assert result["ok"] is True
    assert result["closed"] is True
    assert proc.stdin.closed is True


class _NonWritableStdin:
    async def drain(self) -> None:
        return None


@pytest.mark.asyncio
async def test_write_background_stdin_rejects_non_writable() -> None:
    proc = _ProcWithStdin(pid=7006)
    proc.stdin = _NonWritableStdin()  # type: ignore[assignment]
    info = BackgroundProcessInfo(
        job_id="job-6",
        pid=7006,
        command="cmd",
        session_id="sess-6",
        started_at=1.0,
        status="running",
    )
    entry = BackgroundRegistryEntry(
        info=info,
        proc=cast(AsyncProcessProtocol, proc),
        stdout_buffer=deque(),
        stderr_buffer=deque(),
    )
    result = await write_background_stdin(entry, "y")
    assert result["ok"] is False
    assert result["error"] == "stdin_not_writable"


@pytest.mark.asyncio
async def test_bash_process_tool_write_stdin_and_close_stdin() -> None:
    proc = _ProcWithStdin(pid=7011)
    registry = get_background_registry()
    await registry.register(
        cast(AsyncProcessProtocol, proc),
        command="cat",
        session_id="stdin-actions",
    )

    tool = create_bash_process_tool()
    config = {"configurable": {"context": {"session_id": "stdin-actions"}}}

    write_result = await tool.ainvoke(
        {"action": "write_stdin", "pid": 7011, "data": "raw"},
        config=config,
    )
    assert write_result["metadata"]["ok"] is True
    assert proc.stdin.chunks == [b"raw"]

    close_result = await tool.ainvoke(
        {"action": "close_stdin", "pid": 7011},
        config=config,
    )
    assert close_result["metadata"]["ok"] is True
    assert proc.stdin.closed is True


@pytest.mark.asyncio
async def test_bash_process_tool_submit_stdin_end_to_end() -> None:
    proc = _ProcWithStdin(pid=7010)
    registry = get_background_registry()
    await registry.register(
        cast(AsyncProcessProtocol, proc),
        command="npm create vite",
        session_id="stdin-e2e",
    )

    tool = create_bash_process_tool()
    config = {"configurable": {"context": {"session_id": "stdin-e2e"}}}
    result = await tool.ainvoke(
        {"action": "submit_stdin", "pid": 7010, "data": "y"},
        config=config,
    )

    assert result["metadata"]["ok"] is True
    assert proc.stdin.chunks == [b"y\n"]
    stdin_result = cast(dict[str, object], result["content"])
    assert stdin_result.get("ok") is True
