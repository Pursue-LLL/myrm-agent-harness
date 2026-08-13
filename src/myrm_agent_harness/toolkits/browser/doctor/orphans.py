"""Browser Doctor — orphan automation process detection and cleanup.

Precisely detects orphan patchright/playwright chromium and driver processes
(matches framework cache paths) and safely cleans them up (dry-run by default,
``force=True`` required to kill).

[INPUT]
- psutil (optional, process iteration)
- .report::DoctorCheckResult/CheckStatus (POS: doctor data models)

[OUTPUT]
- find_orphan_chromium_processes / find_orphan_driver_processes / find_orphan_automation_processes: orphan process detection
- cleanup_orphan_processes: safe cleanup (dry-run by default)
- check_orphan_processes: doctor check result for the orphan scan

[POS]
Orphan process detection and cleanup. The psutil process-table walk is
synchronous and offloaded via asyncio.to_thread by callers (doctor orchestrator,
server health endpoints) so it never blocks an event loop.
"""

from __future__ import annotations

import logging
import os
import signal

from .report import CheckStatus, DoctorCheckResult

logger = logging.getLogger(__name__)


def find_orphan_chromium_processes() -> list[dict[str, object]]:
    """Find orphan patchright/playwright chromium processes.

    Precisely identifies browser automation processes by checking:
    - Process name contains "chrom"
    - Command line contains --user-data-dir with playwright/patchright cache path
    - No living Python parent process

    Returns:
        List of orphan process info (pid, name, cmdline, user_data_dir)
    """
    try:
        import psutil
    except (ImportError, TypeError):
        logger.warning("psutil not available, cannot detect orphan processes")
        return []

    orphans: list[dict[str, object]] = []
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


def find_orphan_driver_processes() -> list[dict[str, object]]:
    """Find orphan patchright/playwright driver node processes."""
    try:
        import psutil
    except (ImportError, TypeError):
        logger.warning("psutil not available, cannot detect orphan driver processes")
        return []

    orphans: list[dict[str, object]] = []
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


def find_orphan_automation_processes() -> list[dict[str, object]]:
    """Find orphan browser and driver processes from automation frameworks."""
    seen_pids: set[int] = set()
    combined: list[dict[str, object]] = []

    for orphan in [*find_orphan_chromium_processes(), *find_orphan_driver_processes()]:
        pid = int(orphan["pid"])
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
        current_tree_pids = {
            p.pid for p in [current_proc, *current_proc.children(recursive=True)]
        }

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
    orphan_pids: list[int] | None = None, *, force: bool = False
) -> dict[str, object]:
    """Clean up orphan automation processes with safety checks.

    Args:
        orphan_pids: Optional list of PIDs to kill. If None, auto-detect.
        force: Must be True to actually kill processes (safety mechanism).

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
        orphan_pids = [int(o["pid"]) for o in orphans]

    if not force:
        return {
            "killed": 0,
            "dry_run": True,
            "would_kill": len(orphan_pids),
            "message": "Dry-run mode: use force=True to actually kill processes",
        }

    killed = 0
    failed = []

    for pid in orphan_pids:
        try:
            os.kill(pid, signal.SIGTERM)
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


def check_orphan_processes() -> DoctorCheckResult:
    """Check for orphan automation browser processes (chromium + driver)."""
    orphans = find_orphan_automation_processes()

    if not orphans:
        return DoctorCheckResult(
            name="orphan_processes",
            status=CheckStatus.OK,
            message="No orphan automation processes detected",
            details={"count": 0},
        )

    pids_preview = [o["pid"] for o in orphans[:3]]
    if len(orphans) > 3:
        pids_preview.append("...")

    return DoctorCheckResult(
        name="orphan_processes",
        status=CheckStatus.WARNING,
        message=f"Found {len(orphans)} orphan automation process(es): {pids_preview}",
        fix="python -m myrm_agent_harness.toolkits.browser --cleanup-orphans --force",
        details={
            "count": len(orphans),
            "pids": [o["pid"] for o in orphans],
            "paths": [o["user_data_dir"] for o in orphans],
        },
    )
