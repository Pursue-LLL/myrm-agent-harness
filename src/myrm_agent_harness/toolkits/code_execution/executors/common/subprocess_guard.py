"""Subprocess timeout guard for code executors.

Wraps ``asyncio.subprocess.Process.communicate()`` with a timeout and
graceful termination (SIGTERM → 2 s grace → SIGKILL).  All code execution
modules that spawn subprocesses (docker cp, docker exec, venv creation,
etc.) should use ``guarded_communicate`` instead of bare ``communicate``
to prevent indefinite hangs.

[INPUT]

[OUTPUT]
- (stdout_bytes, stderr_bytes) on success
- SubprocessTimeoutError on timeout (inherits TimeoutError)

[POS]
Single-responsibility guard. Does NOT replace the richer timeout logic
in ``local/executor.py`` which needs process-group kills.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class SubprocessTimeoutError(TimeoutError):
    """Raised when a guarded subprocess exceeds the allowed timeout."""

    def __init__(self, timeout: float, label: str = "") -> None:
        self.timeout = timeout
        self.label = label
        detail = f" ({label})" if label else ""
        super().__init__(f"Subprocess timed out after {timeout}s{detail}")


async def _terminate_process(proc: asyncio.subprocess.Process) -> None:
    """Gracefully terminate: SIGTERM → 2 s wait → SIGKILL."""
    if proc.returncode is not None:
        return
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except TimeoutError:
        proc.kill()
        await proc.wait()


async def guarded_communicate(
    proc: asyncio.subprocess.Process,
    timeout: float,
    *,
    label: str = "",
) -> tuple[bytes, bytes]:
    """``communicate()`` with timeout protection and graceful termination.

    Args:
        proc: The subprocess to communicate with.
        timeout: Maximum seconds to wait.
        label: Human-readable tag for log / error messages.

    Returns:
        ``(stdout_bytes, stderr_bytes)`` on success.

    Raises:
        SubprocessTimeoutError: If the subprocess does not finish in time.
    """
    try:
        return await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        logger.warning("Subprocess timeout after %.0fs: %s (pid=%s)", timeout, label or "unknown", proc.pid)
        await _terminate_process(proc)
        raise SubprocessTimeoutError(timeout, label) from None
