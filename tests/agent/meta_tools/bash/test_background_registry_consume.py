"""Unit tests for background registry stdout/stderr consume loop."""

from __future__ import annotations

import asyncio
from collections import deque
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.bash._background_registry_consume import (
    BackgroundRegistryEntry,
    consume_background_entry,
)
from myrm_agent_harness.agent.meta_tools.bash._background_types import BackgroundProcessInfo
from myrm_agent_harness.toolkits.code_execution.executors.models import AsyncProcessProtocol


class _FakeStream:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)


class _FakeProc:
    def __init__(
        self,
        pid: int,
        stdout: list[bytes],
        stderr: list[bytes] | None = None,
        *,
        stdout_stream: object | None = None,
        stderr_stream: object | None = None,
    ) -> None:
        self._proc = MagicMock()
        self._proc.pid = pid
        self.stdout = stdout_stream if stdout_stream is not None else _FakeStream(stdout)
        self.stderr = stderr_stream if stderr_stream is not None else _FakeStream(stderr or [])
        self._exit_event = asyncio.Event()
        self._exit_code = 0

    async def wait(self) -> int:
        await self._exit_event.wait()
        return self._exit_code

    def finish(self, exit_code: int = 0) -> None:
        self._exit_code = exit_code
        self._exit_event.set()


class _LimitOverrunStream:
    def __init__(self) -> None:
        self._raised = False

    async def readline(self) -> bytes:
        if not self._raised:
            self._raised = True
            raise asyncio.LimitOverrunError("line too long", 4096)
        return b""

    async def readexactly(self, _n: int) -> bytes:
        return b""


class _NoReadlineStream:
    pass


def _make_entry(
    proc: _FakeProc,
    *,
    finish_listener: AsyncMock | None = None,
    progress_listener: AsyncMock | None = None,
    spill_writer: MagicMock | None = None,
) -> BackgroundRegistryEntry:
    info = BackgroundProcessInfo(
        job_id="a" * 32,
        pid=proc._proc.pid,
        command="echo test",
        session_id="sess-consume",
        started_at=1.0,
        status="running",
    )
    return BackgroundRegistryEntry(
        info=info,
        proc=cast(AsyncProcessProtocol, proc),
        stdout_buffer=deque(maxlen=200),
        stderr_buffer=deque(maxlen=200),
        finish_listener=finish_listener,
        progress_listener=progress_listener,
        spill_writer=spill_writer,
    )


async def _run_consume(entry: BackgroundRegistryEntry) -> tuple[list[int], list[str | None]]:
    reaped: list[int] = []
    cleared: list[str | None] = []

    await consume_background_entry(
        entry,
        snapshot=lambda e: e.info,
        schedule_reap=lambda pid: reaped.append(pid),
        clear_session_if_idle=lambda sid: cleared.append(sid),
    )
    return reaped, cleared


@pytest.mark.asyncio
async def test_consume_background_entry_captures_stdout_and_exits() -> None:
    proc = _FakeProc(pid=4242, stdout=[b"hello\n"], stderr=[])
    entry = _make_entry(proc)

    task = asyncio.create_task(_run_consume(entry))
    await asyncio.sleep(0.05)
    proc.finish(exit_code=0)
    reaped, cleared = await task

    assert entry.info.status == "exited"
    assert entry.info.exit_code == 0
    assert [text for _, text in entry.stdout_buffer] == ["hello"]
    assert reaped == [4242]
    assert cleared == ["sess-consume"]


@pytest.mark.asyncio
async def test_consume_background_entry_invokes_finish_listener() -> None:
    proc = _FakeProc(pid=7777, stdout=[b"done\n"], stderr=[])
    listener = AsyncMock()
    entry = _make_entry(proc, finish_listener=listener)

    task = asyncio.create_task(_run_consume(entry))
    await asyncio.sleep(0.05)
    proc.finish(exit_code=0)
    await task

    listener.assert_awaited_once()


@pytest.mark.asyncio
async def test_consume_background_entry_persists_terminal_state() -> None:
    proc = _FakeProc(pid=8888, stdout=[b"line\n"], stderr=[])
    entry = _make_entry(proc)

    with patch(
        "myrm_agent_harness.agent.meta_tools.bash._background_registry_store_sync.persist_terminal_state",
    ) as persist:
        task = asyncio.create_task(_run_consume(entry))
        await asyncio.sleep(0.05)
        proc.finish(exit_code=0)
        await task

    persist.assert_called_once_with(entry.info)


@pytest.mark.asyncio
async def test_consume_background_entry_captures_stderr() -> None:
    proc = _FakeProc(pid=1111, stdout=[], stderr=[b"warn\n"])
    entry = _make_entry(proc)

    task = asyncio.create_task(_run_consume(entry))
    await asyncio.sleep(0.05)
    proc.finish(exit_code=1)
    await task

    assert [text for _, text in entry.stderr_buffer] == ["warn"]
    assert entry.info.exit_code == 1


@pytest.mark.asyncio
async def test_consume_background_entry_truncates_long_lines() -> None:
    long_payload = b"x" * 33_000 + b"\n"
    proc = _FakeProc(pid=2222, stdout=[long_payload], stderr=[])
    entry = _make_entry(proc)

    task = asyncio.create_task(_run_consume(entry))
    await asyncio.sleep(0.05)
    proc.finish()
    await task

    captured = entry.stdout_buffer[0][1]
    assert "bytes truncated" in captured
    assert len(captured) <= 32 * 1024 + 64


@pytest.mark.asyncio
async def test_consume_background_entry_emits_progress() -> None:
    progress_line = b'MYRM_PROGRESS {"percent": 50, "message": "Building"}\n'
    proc = _FakeProc(pid=3333, stdout=[progress_line], stderr=[])
    progress_listener = AsyncMock()
    entry = _make_entry(proc, progress_listener=progress_listener)

    task = asyncio.create_task(_run_consume(entry))
    await asyncio.sleep(0.05)
    proc.finish()
    await task

    progress_listener.assert_awaited_once()
    assert entry.info.last_progress is not None
    assert entry.info.last_progress.get("progress") == 50


@pytest.mark.asyncio
async def test_consume_background_entry_spill_writer_persists_vault_ref() -> None:
    spill = MagicMock()
    spill.vault_log_ref = "output_spill.txt"
    proc = _FakeProc(pid=4444, stdout=[b"spilled\n"], stderr=[])
    entry = _make_entry(proc, spill_writer=spill)

    with patch(
        "myrm_agent_harness.agent.meta_tools.bash._background_registry_store_sync.persist_vault_log_ref",
    ) as persist_ref:
        task = asyncio.create_task(_run_consume(entry))
        await asyncio.sleep(0.05)
        proc.finish()
        await task

    spill.append_line.assert_called_once_with("stdout", "spilled")
    persist_ref.assert_called_once_with(entry.info)
    assert entry.info.vault_log_ref == "output_spill.txt"


@pytest.mark.asyncio
async def test_consume_background_entry_handles_limit_overrun() -> None:
    overrun = _LimitOverrunStream()
    proc = _FakeProc(
        pid=5555,
        stdout=[],
        stderr=[],
        stdout_stream=overrun,
        stderr_stream=_FakeStream([]),
    )
    entry = _make_entry(proc)

    task = asyncio.create_task(_run_consume(entry))
    await asyncio.sleep(0.05)
    proc.finish()
    await task

    assert entry.stdout_buffer
    assert "truncated" in entry.stdout_buffer[0][1]


@pytest.mark.asyncio
async def test_consume_background_entry_skips_stream_without_readline() -> None:
    proc = _FakeProc(
        pid=6666,
        stdout=[],
        stderr=[],
        stdout_stream=_NoReadlineStream(),
        stderr_stream=_NoReadlineStream(),
    )
    entry = _make_entry(proc)

    task = asyncio.create_task(_run_consume(entry))
    await asyncio.sleep(0.05)
    proc.finish()
    await task

    assert entry.stdout_buffer == deque([])
    assert entry.info.status == "exited"


@pytest.mark.asyncio
async def test_consume_background_entry_cancelled_returns_without_crash() -> None:
    proc = _FakeProc(pid=9999, stdout=[b"block\n"], stderr=[])
    entry = _make_entry(proc)
    reaped: list[int] = []

    task = asyncio.create_task(
        consume_background_entry(
            entry,
            snapshot=lambda e: e.info,
            schedule_reap=lambda pid: reaped.append(pid),
            clear_session_if_idle=lambda _sid: None,
        )
    )
    await asyncio.sleep(0.02)
    task.cancel()
    await task

    assert reaped == [9999]
