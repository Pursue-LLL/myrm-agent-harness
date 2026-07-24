"""Unit tests for PTY background spawn helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.code_execution.executors.local._background_pty_spawn import (
    _PtyProcessWrapper,
    _PtyStdinWriter,
    pty_spawn_eligible,
)


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
