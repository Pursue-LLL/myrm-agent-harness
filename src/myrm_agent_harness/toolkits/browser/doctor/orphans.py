"""Browser Doctor — orphan automation process detection and cleanup.

Precisely detects orphan patchright/playwright chromium and driver processes
(matches framework cache paths) and safely cleans them up (dry-run by default,
``force=True`` required to kill).

[INPUT]
- psutil (optional, process iteration)

[OUTPUT]
- find_orphan_chromium_processes / find_orphan_driver_processes / find_orphan_automation_processes: orphan process detection
- cleanup_orphan_processes: safe cleanup (dry-run by default, SIGTERM/SIGKILL escalation)
- OrphanProcess / OrphanCleanupResult / KillFailure: typed shapes of the scan and cleanup results
- register_browser_exit_reaper / unregister_browser_exit_reaper: atexit emergency reaper lifecycle hooks

[POS]
Orphan process detection and cleanup. The psutil process-table walk is
synchronous and offloaded via asyncio.to_thread by callers (doctor orchestrator,
server health endpoints) so it never blocks an event loop.
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import os
import signal
import time
from typing import TypedDict

logger = logging.getLogger(__name__)


class OrphanProcess(TypedDict):
    """A leftover automation browser or driver process."""

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


def find_orphan_chromium_processes() -> list[OrphanProcess]:
    """Find orphan patchright/playwright chromium processes.

    Precisely identifies browser automation processes by checking:
    - Process name contains "chrom"
    - Command line contains --user-data-dir with playwright/patchright cache path
    - No living Python parent process

    Returns:
        List of orphan process info (pid, name, ppid, user_data_dir)
    """
    try:
        import psutil
    except (ImportError, TypeError):
        logger.warning("psutil not available, cannot detect orphan processes")
        return []

    orphans: list[OrphanProcess] = []
    current_pid = os.getpid()

    try:
        for proc in psutil.process_iter(["pid", "name", "ppid", "cmdline"]):
            try:
                name = proc.info["name"]
                if not name or "chrom" not in name.lower():
                    continue

                cmdline = proc.info.get("cmdline") or []
                if not cmdline:
                    continue

                full_cmd = " ".join(cmdline)

                if "--user-data-dir" not in full_cmd:
                    continue

                user_data_dir = _extract_user_data_dir(full_cmd)
                if not user_data_dir:
                    continue

                if not _is_automation_cache_path(user_data_dir):
                    continue

                if _has_python_ancestor(proc, current_pid):
                    continue

                orphans.append(
                    {
                        "pid": proc.info["pid"],
                        "name": name,
                        "ppid": proc.info["ppid"],
                        "user_data_dir": user_data_dir,
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as exc:
        logger.warning(f"Failed to scan for orphan processes: {exc}")

    return orphans


def find_orphan_driver_processes() -> list[OrphanProcess]:
    """Find orphan patchright/playwright driver node processes."""
    try:
        import psutil
    except (ImportError, TypeError):
        logger.warning("psutil not available, cannot detect orphan driver processes")
        return []

    orphans: list[OrphanProcess] = []
    current_pid = os.getpid()

    try:
        for proc in psutil.process_iter(["pid", "name", "ppid", "cmdline"]):
            try:
                cmdline = proc.info.get("cmdline") or []
                if not cmdline:
                    continue

                full_cmd = " ".join(cmdline)
                if not _is_automation_driver_cmdline(full_cmd):
                    continue

                if _has_python_ancestor(proc, current_pid):
                    continue

                orphans.append(
                    {
                        "pid": proc.info["pid"],
                        "name": proc.info.get("name") or "node",
                        "ppid": proc.info["ppid"],
                        "user_data_dir": "",
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as exc:
        logger.warning(f"Failed to scan for orphan driver processes: {exc}")

    return orphans


def find_orphan_automation_processes() -> list[OrphanProcess]:
    """Find orphan browser and driver processes from automation frameworks."""
    seen_pids: set[int] = set()
    combined: list[OrphanProcess] = []

    for orphan in [*find_orphan_chromium_processes(), *find_orphan_driver_processes()]:
        pid = orphan["pid"]
        if pid in seen_pids:
            continue
        seen_pids.add(pid)
        combined.append(orphan)

    return combined


def _extract_user_data_dir(cmdline: str) -> str:
    """Extract user-data-dir path from command line."""
    if "--user-data-dir=" in cmdline:
        parts = cmdline.split("--user-data-dir=", 1)
        if len(parts) > 1:
            path_part = parts[1].strip().split()[0] if parts[1].strip() else ""
            return path_part
    elif "--user-data-dir" in cmdline:
        parts = cmdline.split("--user-data-dir", 1)
        if len(parts) > 1:
            tokens = parts[1].strip().split()
            if tokens:
                return tokens[0]
    return ""


def _is_automation_cache_path(path: str) -> bool:
    """Check if path is from browser automation framework."""
    automation_markers = [
        ".cache/patchright",
        ".cache/ms-playwright",
        ".cache/puppeteer",
        "playwright_chromium",
        "com.google.chrome.code_sign_clone",
        "chrome_e2e",
        "myrm_chrome_e2e",
    ]
    path_lower = path.lower()
    return any(marker in path_lower for marker in automation_markers)


def _is_automation_driver_cmdline(full_cmd: str) -> bool:
    """Check if command line is a patchright/playwright driver helper."""
    driver_markers = (
        "patchright/driver/node",
        "playwright/driver/node",
        "run-driver",
    )
    cmd_lower = full_cmd.lower()
    return any(marker in cmd_lower for marker in driver_markers)


def _has_python_ancestor(proc: object, current_pid: int) -> bool:
    """Check if process has a Python ancestor.

    Returns True if any ancestor process name contains 'python', or if the
    process is in the current process tree. Returns False if confirmed no
    Python ancestor. Returns True on unexpected errors (conservative default).
    """
    try:
        import psutil

        current_proc = psutil.Process(current_pid)
        current_tree_pids = {p.pid for p in [current_proc, *current_proc.children(recursive=True)]}

        if not isinstance(proc, psutil.Process):
            return False

        parent = proc.parent()
        while parent:
            if parent.pid in current_tree_pids:
                return True

            try:
                if "python" in parent.name().lower():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break

            try:
                parent = parent.parent()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break

        return False
    except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
        return False
    except Exception as exc:
        logger.warning(f"Unexpected error in _has_python_ancestor: {exc}")
        return True


def cleanup_orphan_processes(
    orphan_pids: list[int] | None = None,
    *,
    force: bool = False,
    timeout_s: float = 0.0,
) -> OrphanCleanupResult:
    """Clean up orphan automation processes with safety checks.

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
        orphans = find_orphan_automation_processes()
        orphan_pids = [o["pid"] for o in orphans]

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
        try:
            os.kill(pid, signal.SIGTERM)
            if timeout_s > 0.0:
                deadline = time.time() + timeout_s
                terminated = False
                while time.time() < deadline:
                    try:
                        os.kill(pid, 0)
                        time.sleep(0.05)
                    except ProcessLookupError:
                        terminated = True
                        break
                if not terminated:
                    try:
                        os.kill(pid, signal.SIGKILL)
                        logger.info(f"Force killed (SIGKILL) stubborn orphan process: {pid}")
                    except ProcessLookupError:
                        pass
                try:
                    os.kill(pid, 0)
                    failed.append({"pid": pid, "reason": "process_still_running_after_kill"})
                    continue
                except ProcessLookupError:
                    pass
            killed += 1
            logger.info(f"Killed orphan automation process: {pid}")
        except ProcessLookupError:
            logger.debug(f"Process {pid} already terminated")
        except PermissionError:
            failed.append({"pid": pid, "reason": "permission_denied"})
        except Exception as exc:
            failed.append({"pid": pid, "reason": str(exc)})

    return {
        "killed": killed,
        "dry_run": False,
        "failed": failed,
    }


_exit_reaper_registered: bool = False


def _emergency_cleanup_orphans_on_exit() -> None:
    """Best-effort emergency cleanup registered via atexit.

    Sweeps orphan browser and driver automation processes when the interpreter exits,
    preventing detached Chromium zombies from persisting after unexpected process termination.
    """
    if os.environ.get("MYRM_BROWSER_EXIT_REAP_DISABLED", "").strip().lower() in ("1", "true", "yes"):
        return
    try:
        cleanup_orphan_processes(force=True, timeout_s=0.5)
    except Exception as exc:
        logger.debug(f"atexit emergency orphan cleanup swallowed exception: {exc}")


def register_browser_exit_reaper() -> bool:
    """Register the atexit emergency browser orphan cleanup hook idempotently.

    Returns:
        True if the hook was newly registered, False if already registered.
    """
    global _exit_reaper_registered
    if _exit_reaper_registered:
        return False

    atexit.register(_emergency_cleanup_orphans_on_exit)
    _exit_reaper_registered = True
    return True


def unregister_browser_exit_reaper() -> bool:
    """Unregister the atexit emergency browser orphan cleanup hook if registered.

    Returns:
        True if the hook was unregistered, False if it was not registered.
    """
    global _exit_reaper_registered
    if not _exit_reaper_registered:
        return False

    with contextlib.suppress(Exception):
        atexit.unregister(_emergency_cleanup_orphans_on_exit)
    _exit_reaper_registered = False
    return True
