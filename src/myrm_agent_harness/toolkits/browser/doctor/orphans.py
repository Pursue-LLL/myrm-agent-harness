"""Browser Doctor — leftover automation process detection and cleanup.

A browser launched by the toolkit carries an ownership stamp (see ``process_owner``); it is
a leftover when the process that launched it no longer runs. Processes without a stamp, with an
unreadable environment or with a malformed stamp are never reported and never signalled. Cleanup is
dry-run by default (``force=True`` required) and re-verifies each pid right before signalling it.

[INPUT]
- psutil (optional, process iteration)
- ..process_owner::read_owner_state / OwnerState (POS: ownership stamp classification)

[OUTPUT]
- find_orphan_automation_processes: stamped browser processes whose owner is gone
- cleanup_orphan_processes: safe cleanup (dry-run by default, SIGTERM/SIGKILL escalation)
- OrphanProcess / OrphanCleanupResult / KillFailure: typed shapes of the scan and cleanup results

[POS]
Orphan process detection and cleanup. The psutil process-table walk is
synchronous and offloaded via asyncio.to_thread by callers (doctor orchestrator,
server health endpoints) so it never blocks an event loop.
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import time
from typing import TypedDict

from ..process_owner import OwnerState, read_owner_state

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 0.05
# SIGKILL cannot be caught, but delivery and teardown are asynchronous.
_SIGKILL_SETTLE_S = 1.0


class OrphanProcess(TypedDict):
    """A leftover automation browser process."""

    pid: int
    name: str
    ppid: int
    user_data_dir: str


class KillFailure(TypedDict):
    """A process that could not be terminated."""

    pid: int
    reason: str


class OrphanCleanupResult(TypedDict, total=False):
    """Outcome of ``cleanup_orphan_processes``; the keys present depend on the mode (unavailable, dry-run, kill)."""

    killed: int
    dry_run: bool
    would_kill: int
    message: str
    error: str
    failed: list[KillFailure]


def find_orphan_automation_processes() -> list[OrphanProcess]:
    """Find browser processes whose launching process is gone.

    Only processes carrying an ownership stamp whose owner no longer runs are reported;
    the calling process is never reported.

    Returns:
        List of orphan process info (pid, name, ppid, user_data_dir)
    """
    try:
        import psutil
    except ImportError:
        logger.warning("psutil not available, cannot detect orphan processes")
        return []

    orphans: list[OrphanProcess] = []
    own_pid = os.getpid()
    try:
        for proc in psutil.process_iter():
            if proc.pid == own_pid:
                continue
            try:
                if read_owner_state(proc) is not OwnerState.OWNER_GONE:
                    continue
                orphans.append(
                    {
                        "pid": proc.pid,
                        "name": proc.name(),
                        "ppid": proc.ppid(),
                        "user_data_dir": _extract_user_data_dir(" ".join(proc.cmdline())),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as exc:
        logger.warning(f"Failed to scan for orphan processes: {exc}")

    return orphans


def _extract_user_data_dir(cmdline: str) -> str:
    """Extract the ``--user-data-dir`` value (``=`` or space separated) from a command line, or ``""``."""
    for flag in ("--user-data-dir=", "--user-data-dir"):
        _, found, rest = cmdline.partition(flag)
        if found:
            tokens = rest.split()
            return tokens[0] if tokens else ""
    return ""


def _is_running(pid: int) -> bool:
    """Whether ``pid`` is a live process; an exited process that has not been reaped yet counts as stopped."""
    import psutil

    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _is_leftover(pid: int) -> bool:
    """Re-verify a pid right before signalling it; the process table may have changed since the scan."""
    import psutil

    if pid == os.getpid():
        return False
    try:
        return read_owner_state(psutil.Process(pid)) is OwnerState.OWNER_GONE
    except psutil.NoSuchProcess:
        return False


def _wait_until_stopped(pid: int, timeout_s: float) -> bool:
    """Poll until ``pid`` has stopped; False when it still runs after ``timeout_s``."""
    deadline = time.monotonic() + timeout_s
    while _is_running(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(_POLL_INTERVAL_S)
    return True


def _terminate(pid: int, timeout_s: float) -> bool:
    """SIGTERM ``pid``; with a grace period, escalate to SIGKILL. True when it stopped (or no grace period was asked)."""
    os.kill(pid, signal.SIGTERM)
    if timeout_s <= 0.0 or _wait_until_stopped(pid, timeout_s):
        return True
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)
        logger.info(f"Force killed (SIGKILL) stubborn orphan process: {pid}")
    return _wait_until_stopped(pid, _SIGKILL_SETTLE_S)


def cleanup_orphan_processes(
    orphan_pids: list[int] | None = None,
    *,
    force: bool = False,
    timeout_s: float = 0.0,
) -> OrphanCleanupResult:
    """Clean up orphan automation processes with safety checks.

    Each pid is re-verified as a leftover immediately before it is signalled; a pid that no longer
    is one (pid reuse, owner alive again) is reported as ``not_an_orphan`` and left alone.

    Args:
        orphan_pids: Optional list of PIDs to kill. If None, auto-detect.
        force: Must be True to actually kill processes (safety mechanism).
        timeout_s: Grace period in seconds to wait after SIGTERM before SIGKILL.
                   Defaults to 0.0 (immediate SIGTERM only, non-blocking).

    Returns:
        Result dict with killed count, dry_run flag, would_kill (dry-run), and details.
    """
    import importlib.util

    if importlib.util.find_spec("psutil") is None:
        return {
            "killed": 0,
            "dry_run": True,
            "error": "psutil not available",
        }

    if orphan_pids is None:
        orphan_pids = [o["pid"] for o in find_orphan_automation_processes()]

    if not force:
        return {
            "killed": 0,
            "dry_run": True,
            "would_kill": len(orphan_pids),
            "message": "Dry-run mode: use force=True to actually kill processes",
        }

    killed = 0
    failed: list[KillFailure] = []

    for pid in orphan_pids:
        if not _is_leftover(pid):
            if _is_running(pid):
                failed.append({"pid": pid, "reason": "not_an_orphan"})
            else:
                logger.debug(f"Process {pid} already terminated")
            continue
        try:
            stopped = _terminate(pid, timeout_s)
        except ProcessLookupError:
            logger.debug(f"Process {pid} already terminated")
            continue
        except PermissionError:
            failed.append({"pid": pid, "reason": "permission_denied"})
            continue
        except Exception as exc:
            failed.append({"pid": pid, "reason": str(exc)})
            continue

        if stopped:
            killed += 1
            logger.info(f"Killed orphan automation process: {pid}")
        else:
            failed.append({"pid": pid, "reason": "process_still_running_after_kill"})

    return {
        "killed": killed,
        "dry_run": False,
        "failed": failed,
    }
