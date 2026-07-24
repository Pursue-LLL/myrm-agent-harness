"""Optional POSIX PTY spawn for background bash jobs (PIPE fallback elsewhere).

[INPUT]
- executors.base::ExecutionContext
- executors.models::AsyncProcessProtocol

[OUTPUT]
- try_spawn_background_pty: Spawn with merged stdout/stderr on a PTY master fd

[POS]
PTY adapter for interactive CLIs (npm create, python input()). Skipped when
sandbox wrapping is active or on non-POSIX hosts; callers fall back to PIPE.
"""

from __future__ import annotations

import asyncio
import logging
import os
import pty
import signal
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from myrm_agent_harness.toolkits.code_execution.executors.base import ExecutionContext
from myrm_agent_harness.toolkits.code_execution.executors.models import (
    AsyncProcessProtocol,
)

logger = logging.getLogger(__name__)

_STREAM_LIMIT_BYTES = 8 * 1024 * 1024


class _PtyStdinWriter:
    """Write-only stdin shim over a PTY master fd."""

    def __init__(self, master_fd: int) -> None:
        self._fd = master_fd
        self._closed = False

    def write(self, data: bytes) -> None:
        if self._closed:
            raise BrokenPipeError("PTY stdin is closed")
        os.write(self._fd, data)

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def close(self) -> None:
        self._closed = True

    async def wait_closed(self) -> None:
        return None


class _PtyProcessWrapper(AsyncProcessProtocol):
    """AsyncProcessProtocol backed by a subprocess attached to a PTY slave."""

    def __init__(
        self,
        proc: asyncio.subprocess.Process,
        *,
        master_fd: int,
        stdout_reader: asyncio.StreamReader,
        read_transport: asyncio.BaseTransport,
        read_file: object,
    ) -> None:
        self._proc = proc
        self._master_fd = master_fd
        self._stdout_reader = stdout_reader
        self._read_transport = read_transport
        self._read_file = read_file

    @property
    def stdin(self) -> _PtyStdinWriter:
        return _PtyStdinWriter(self._master_fd)

    @property
    def stdout(self) -> asyncio.StreamReader:
        return self._stdout_reader

    @property
    def stderr(self) -> None:
        return None

    async def wait(self) -> int:
        return await self._proc.wait()

    def terminate(self) -> None:
        from myrm_agent_harness.utils import os_compat

        os_compat.kill_process_group(self._proc.pid, signal.SIGTERM)

    def kill(self) -> None:
        from myrm_agent_harness.utils import os_compat

        os_compat.kill_process_group(self._proc.pid, signal.SIGKILL)


def pty_spawn_eligible(*, sandbox_enabled: bool) -> bool:
    """PTY is only attempted on POSIX hosts without OS-level sandbox wrapping."""
    return os.name != "nt" and not sandbox_enabled


async def _connect_pty_reader(master_fd: int) -> tuple[asyncio.StreamReader, asyncio.BaseTransport, object]:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=_STREAM_LIMIT_BYTES)
    protocol = asyncio.StreamReaderProtocol(reader)
    read_file = os.fdopen(master_fd, "rb", buffering=0)
    transport, _ = await loop.connect_read_pipe(lambda: protocol, read_file)
    return reader, transport, read_file


async def try_spawn_background_pty(
    *,
    full_cmd_array: list[str],
    effective_cwd: Path | None,
    env: dict[str, str],
    preexec_fn: Callable[[], None] | None,
    process_group_kwargs: dict[str, object],
) -> AsyncProcessProtocol | None:
    """Spawn via PTY; returns None when the platform cannot create a PTY pair."""
    try:
        master_fd, slave_fd = pty.openpty()
    except OSError as exc:
        logger.debug("PTY openpty unavailable: %s", exc)
        return None

    read_transport: asyncio.BaseTransport | None = None
    read_file: object | None = None
    proc: asyncio.subprocess.Process | None = None

    try:
        kwargs = dict(process_group_kwargs)
        kwargs.setdefault("limit", _STREAM_LIMIT_BYTES)
        if os.name != "nt" and preexec_fn is not None:
            kwargs["preexec_fn"] = preexec_fn

        proc = await asyncio.create_subprocess_exec(
            *full_cmd_array,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=str(effective_cwd) if effective_cwd else None,
            env=env,
            **kwargs,
        )
    except OSError as exc:
        logger.warning("PTY subprocess spawn failed: %s", exc)
        with suppress(OSError):
            os.close(master_fd)
        with suppress(OSError):
            os.close(slave_fd)
        return None
    finally:
        with suppress(OSError):
            os.close(slave_fd)

    if proc is None:
        with suppress(OSError):
            os.close(master_fd)
        return None

    stdout_reader, read_transport, read_file = await _connect_pty_reader(master_fd)
    logger.info(" [LocalExecutor] Background PTY spawn pid=%s", proc.pid)
    return _PtyProcessWrapper(
        proc,
        master_fd=master_fd,
        stdout_reader=stdout_reader,
        read_transport=read_transport,
        read_file=read_file,
    )


__all__ = ["pty_spawn_eligible", "try_spawn_background_pty"]
