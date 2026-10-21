"""Unit tests for PTY background spawn helpers."""

from __future__ import annotations

import asyncio
import errno
import os
import sys
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.code_execution.executors.local._background_pty_spawn import (
    _PtyProcessWrapper,
    _PtyReaderProtocol,
    _PtyStdinWriter,
    pty_spawn_eligible,
    try_spawn_background_pty,
)
from myrm_agent_harness.utils import os_compat


def test_pty_spawn_eligible_skips_sandbox_and_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("os.name", "posix")
    assert pty_spawn_eligible(sandbox_enabled=False) is True
    assert pty_spawn_eligible(sandbox_enabled=True) is False
    monkeypatch.setattr("os.name", "nt")
    assert pty_spawn_eligible(sandbox_enabled=False) is False


def test_pty_stdin_writer_close_sends_eot() -> None:
    import os

    read_fd, write_fd = os.pipe()
    try:
        writer = _PtyStdinWriter(write_fd)
        writer.close()
        payload = os.read(read_fd, 8)
        assert payload == b"\x04"
        with pytest.raises(BrokenPipeError):
            writer.write(b"x")
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_pty_process_wrapper_reuses_single_stdin_writer() -> None:
    proc = MagicMock()
    proc.pid = 123
    reader = MagicMock()
    wrapper = _PtyProcessWrapper(
        proc,
        master_fd=99,
        stdout_reader=reader,
        read_transport=MagicMock(),
        read_file=MagicMock(),
    )
    assert wrapper.stdin is wrapper.stdin


@pytest.mark.asyncio
async def test_pty_reader_protocol_keeps_buffered_lines_when_linux_reports_eio() -> None:
    """Linux fails the master read with EIO once the slave closes; buffered lines must still be delivered."""
    reader = asyncio.StreamReader()
    protocol = _PtyReaderProtocol(reader)
    reader.feed_data(b"line1\nline2\n")

    protocol.connection_lost(OSError(errno.EIO, "Input/output error"))

    assert await reader.readline() == b"line1\n"
    assert await reader.readline() == b"line2\n"
    assert await reader.readline() == b""


@pytest.mark.asyncio
async def test_pty_reader_protocol_still_surfaces_other_read_errors() -> None:
    reader = asyncio.StreamReader()
    protocol = _PtyReaderProtocol(reader)

    protocol.connection_lost(OSError(errno.EBADF, "Bad file descriptor"))

    with pytest.raises(OSError, match="Bad file descriptor"):
        await reader.readline()


@pytest.mark.asyncio
async def test_spawned_pty_output_survives_child_exit() -> None:
    """Every line of a short-lived child is readable after it exits, followed by a clean EOF."""
    process = await try_spawn_background_pty(
        full_cmd_array=[sys.executable, "-c", "print('one'); print('two'); print('three')"],
        effective_cwd=None,
        env={"PATH": os.environ.get("PATH", os.defpath)},
        preexec_fn=None,
        process_group_kwargs=os_compat.get_process_group_kwargs(),
    )
    assert isinstance(process, _PtyProcessWrapper)
    await process.wait()

    lines: list[bytes] = []
    while line := await asyncio.wait_for(process.stdout.readline(), timeout=5):
        lines.append(line.strip())

    assert lines == [b"one", b"two", b"three"]
