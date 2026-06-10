"""Browser Doctor - Pre-flight diagnostics and health checks.

[INPUT]
- patchright (POS: Browser automation library)
- psutil (POS: System monitoring)
- pathlib::Path (POS: File system operations)

[OUTPUT]
- CheckStatus: Check result status enum (OK, WARNING, ERROR, MISSING)
- DoctorCheckResult: Single check result with status and message
- DoctorReport: Complete diagnostic report with all checks
- run_doctor: Main diagnostic function
- format_report: Render report as colored CLI output
- find_orphan_chromium_processes: Detect orphan Chromium processes (patchright/playwright/puppeteer caches)
- find_orphan_driver_processes: Detect orphan patchright/playwright driver node processes
- find_orphan_automation_processes: Combined orphan browser + driver scan
- cleanup_orphan_processes: Safe cleanup with force flag

[POS]
Browser toolkit diagnostics module. Validates dependencies, configuration,
environment, and browser launchability before actual operations.
Provides clear fix suggestions for each failure.
Includes precise orphan process detection (matches patchright/playwright cache paths)
with safety mechanisms (dry-run default, force flag required for cleanup).
"""

from __future__ import annotations

import logging
import os
import signal
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)


class CheckStatus(StrEnum):
    """Status of a diagnostic check."""

    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class DoctorCheckResult:
    """Result of a single diagnostic check."""

    name: str
    status: CheckStatus
    message: str
    fix: str | None = None
    details: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Complete diagnostic report."""

    checks: dict[str, DoctorCheckResult]
    summary: str
    overall_healthy: bool
    recommendations: list[str] = field(default_factory=list)


def _check_patchright() -> DoctorCheckResult:
    """Check if patchright is installed and get version."""
    try:
        import patchright

        version = getattr(patchright, "__version__", "unknown")
        return DoctorCheckResult(
            name="patchright",
            status=CheckStatus.OK,
            message=f"patchright {version} installed",
            details={"version": version},
        )
    except (ImportError, TypeError):
        return DoctorCheckResult(
            name="patchright",
            status=CheckStatus.ERROR,
            message="patchright not installed",
            fix="uv add patchright",
        )


def _check_browser_executable(executable_path_str: str = "") -> DoctorCheckResult:
    """Check if browser executable exists and is executable."""
    executable_path_str = executable_path_str.strip()

    if not executable_path_str:
        return DoctorCheckResult(
            name="browser_executable",
            status=CheckStatus.OK,
            message="Using patchright bundled browser (default)",
            details={"source": "bundled"},
        )

    executable_path = Path(executable_path_str).expanduser()

    if not executable_path.exists():
        return DoctorCheckResult(
            name="browser_executable",
            status=CheckStatus.ERROR,
            message=f"Browser executable not found: {executable_path}",
            fix=f"Remove invalid BROWSER_EXECUTABLE_PATH or install browser at {executable_path}",
            details={"path": str(executable_path), "exists": False},
        )

    if not os.access(executable_path, os.X_OK):
        return DoctorCheckResult(
            name="browser_executable",
            status=CheckStatus.ERROR,
            message=f"Browser executable not executable: {executable_path}",
            fix=f"chmod +x {executable_path}",
            details={"path": str(executable_path), "executable": False},
        )

    return DoctorCheckResult(
        name="browser_executable",
        status=CheckStatus.OK,
        message=f"Browser executable: {executable_path}",
        details={"path": str(executable_path), "source": "custom"},
    )


def _check_memory() -> DoctorCheckResult:
    """Check system memory availability."""
    try:
        import psutil
    except (ImportError, TypeError):
        return DoctorCheckResult(
            name="memory",
            status=CheckStatus.WARNING,
            message="psutil not installed, cannot check memory",
            fix="uv sync --all-extras",
        )

    memory = psutil.virtual_memory()
    available_gb = memory.available / (1024**3)
    total_gb = memory.total / (1024**3)
    used_percent = memory.percent

    if available_gb < 1.0:
        return DoctorCheckResult(
            name="memory",
            status=CheckStatus.ERROR,
            message=f"Low memory: {available_gb:.1f} GB available ({used_percent:.0f}% used)",
            fix="Close other applications or increase system RAM",
            details={
                "available_gb": round(available_gb, 2),
                "total_gb": round(total_gb, 2),
                "used_percent": used_percent,
            },
        )

    if available_gb < 2.0:
        return DoctorCheckResult(
            name="memory",
            status=CheckStatus.WARNING,
            message=f"Memory tight: {available_gb:.1f} GB available ({used_percent:.0f}% used)",
            fix="Consider closing other applications for better stability",
            details={
                "available_gb": round(available_gb, 2),
                "total_gb": round(total_gb, 2),
                "used_percent": used_percent,
            },
        )

    return DoctorCheckResult(
        name="memory",
        status=CheckStatus.OK,
        message=f"Memory: {available_gb:.1f} GB available ({used_percent:.0f}% used)",
        details={"available_gb": round(available_gb, 2), "total_gb": round(total_gb, 2), "used_percent": used_percent},
    )


def _check_disk() -> DoctorCheckResult:
    """Check disk space availability for temp files and recordings."""
    try:
        import psutil
    except (ImportError, TypeError):
        return DoctorCheckResult(
            name="disk",
            status=CheckStatus.WARNING,
            message="psutil not installed, cannot check disk space",
            fix="uv sync --all-extras",
        )

    try:
        usage = psutil.disk_usage("/tmp")
        available_gb = usage.free / (1024**3)
        used_percent = usage.percent

        if available_gb < 0.5:
            return DoctorCheckResult(
                name="disk",
                status=CheckStatus.ERROR,
                message=f"Low disk space: {available_gb:.1f} GB available ({used_percent:.0f}% used)",
                fix="Clean up /tmp or increase disk space",
                details={"available_gb": round(available_gb, 2), "used_percent": used_percent},
            )

        if available_gb < 1.0:
            return DoctorCheckResult(
                name="disk",
                status=CheckStatus.WARNING,
                message=f"Disk space tight: {available_gb:.1f} GB available ({used_percent:.0f}% used)",
                fix="Consider cleaning up /tmp for better stability",
                details={"available_gb": round(available_gb, 2), "used_percent": used_percent},
            )

        return DoctorCheckResult(
            name="disk",
            status=CheckStatus.OK,
            message=f"Disk space: {available_gb:.1f} GB available ({used_percent:.0f}% used)",
            details={"available_gb": round(available_gb, 2), "used_percent": used_percent},
        )
    except Exception as exc:
        return DoctorCheckResult(
            name="disk",
            status=CheckStatus.WARNING,
            message=f"Cannot check disk space: {exc}",
        )


async def _check_browser_launch(launch_options: dict[str, object] | None = None) -> DoctorCheckResult:
    """Test browser launch and basic functionality."""
    try:
        from patchright.async_api import async_playwright
    except (ImportError, TypeError):
        return DoctorCheckResult(
            name="browser_launch",
            status=CheckStatus.ERROR,
            message="patchright not available for launch test",
            fix="uv add patchright",
        )

    launch_opts = launch_options or {
        "headless": True,
        "args": ["--no-sandbox", "--disable-dev-shm-usage"],
    }

    try:
        playwright = await async_playwright().start()
        try:
            browser = await playwright.chromium.launch(**launch_opts)  # type: ignore[arg-type]
            try:
                context = await browser.new_context()
                try:
                    page = await context.new_page()
                    await page.goto("about:blank", timeout=5000)
                    title = await page.title()

                    return DoctorCheckResult(
                        name="browser_launch",
                        status=CheckStatus.OK,
                        message="Browser launch test successful",
                        details={"headless": launch_opts.get("headless"), "title": title},
                    )
                finally:
                    await context.close()
            finally:
                await browser.close()
        finally:
            await playwright.stop()

    except TimeoutError as exc:
        return DoctorCheckResult(
            name="browser_launch",
            status=CheckStatus.ERROR,
            message=f"Browser launch timeout: {exc}",
            fix="Check system resources or network connectivity",
        )
    except Exception as exc:
        error_msg = str(exc).lower()

        if "executable doesn't exist" in error_msg or "not found" in error_msg:
            return DoctorCheckResult(
                name="browser_launch",
                status=CheckStatus.ERROR,
                message=f"Browser executable not found: {exc}",
                fix="Run 'patchright install chromium' or check BROWSER_EXECUTABLE_PATH",
            )

        if "permission denied" in error_msg:
            return DoctorCheckResult(
                name="browser_launch",
                status=CheckStatus.ERROR,
                message=f"Permission denied: {exc}",
                fix="Check file permissions or run with appropriate privileges",
            )

        return DoctorCheckResult(
            name="browser_launch",
            status=CheckStatus.ERROR,
            message=f"Browser launch failed: {exc}",
            fix="Check logs for details, verify dependencies (libgobject, libglib, etc.)",
        )


def _check_proxy(proxy: str = "") -> DoctorCheckResult:
    """Check proxy configuration if set."""
    proxy = proxy.strip()

    if not proxy:
        return DoctorCheckResult(
            name="proxy",
            status=CheckStatus.OK,
            message="No proxy configured (direct connection)",
            details={"configured": False},
        )

    return DoctorCheckResult(
        name="proxy",
        status=CheckStatus.OK,
        message=f"Proxy configured: {proxy}",
        details={"proxy": proxy, "configured": True},
    )


async def _try_auto_install_chromium() -> DoctorCheckResult | None:
    """Attempt to auto-install Chromium via patchright CLI.

    Returns a DoctorCheckResult on success/failure, or None if the patchright
    CLI is not available.
    """
    import asyncio
    import shutil

    if not shutil.which("patchright"):
        return DoctorCheckResult(
            name="auto_install",
            status=CheckStatus.ERROR,
            message="'patchright' CLI not found — cannot auto-install Chromium",
            fix="pip install patchright && patchright install chromium",
        )

    install_timeout = 600  # 10 minutes
    logger.info("Doctor auto_fix: installing Chromium via 'patchright install chromium'...")
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "patchright", "install", "chromium",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=install_timeout,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=install_timeout)

        if proc.returncode == 0:
            return DoctorCheckResult(
                name="auto_install",
                status=CheckStatus.OK,
                message="Chromium auto-installed successfully",
                details={"output": (stdout or b"").decode(errors="replace")[:300]},
            )
        return DoctorCheckResult(
            name="auto_install",
            status=CheckStatus.ERROR,
            message=f"Chromium auto-install failed (exit {proc.returncode})",
            fix="Run 'patchright install chromium' manually",
            details={"stderr": (stderr or b"").decode(errors="replace")[:300]},
        )
    except TimeoutError:
        return DoctorCheckResult(
            name="auto_install",
            status=CheckStatus.ERROR,
            message="Chromium auto-install timed out (10 minutes)",
            fix="Check network connection and disk space, then run 'patchright install chromium' manually",
        )
    except Exception as exc:
        return DoctorCheckResult(
            name="auto_install",
            status=CheckStatus.ERROR,
            message=f"Chromium auto-install failed: {exc}",
            fix="Run 'patchright install chromium' manually",
        )


async def run_doctor(
    *,
    include_launch_test: bool = True,
    include_orphan_check: bool = True,
    auto_fix: bool = False,
    launch_options: dict[str, object] | None = None,
    browser_executable_path: str = "",
    browser_proxy: str = "",
) -> DoctorReport:
    """Run comprehensive browser diagnostics.

    Args:
        include_launch_test: Whether to test actual browser launch
        include_orphan_check: Whether to check for orphan processes
        auto_fix: When True and browser launch fails due to missing executable,
            automatically install Chromium via patchright and re-test.
        launch_options: Optional custom launch options for launch test
        browser_executable_path: Custom browser executable path to check
        browser_proxy: Proxy URL to validate

    Returns:
        DoctorReport with all check results and recommendations
    """
    checks: dict[str, DoctorCheckResult] = {}

    checks["patchright"] = _check_patchright()
    checks["browser_executable"] = _check_browser_executable(browser_executable_path)
    checks["memory"] = _check_memory()
    checks["disk"] = _check_disk()
    checks["proxy"] = _check_proxy(browser_proxy)

    if include_orphan_check:
        checks["orphan_processes"] = _check_orphan_processes()

    if include_launch_test:
        launch_result = await _check_browser_launch(launch_options)
        checks["browser_launch"] = launch_result

        if (
            auto_fix
            and launch_result.status == CheckStatus.ERROR
            and launch_result.fix
            and "patchright install chromium" in launch_result.fix
        ):
            install_result = await _try_auto_install_chromium()
            if install_result:
                checks["auto_install"] = install_result
                if install_result.status == CheckStatus.OK:
                    checks["browser_launch"] = await _check_browser_launch(launch_options)

    ok_count = sum(1 for c in checks.values() if c.status == CheckStatus.OK)
    warning_count = sum(1 for c in checks.values() if c.status == CheckStatus.WARNING)
    error_count = sum(1 for c in checks.values() if c.status == CheckStatus.ERROR)
    missing_count = sum(1 for c in checks.values() if c.status == CheckStatus.MISSING)

    parts = [f"{ok_count}/{len(checks)} checks passed"]
    if warning_count > 0:
        parts.append(f"{warning_count} warnings")
    if error_count > 0:
        parts.append(f"{error_count} errors")
    if missing_count > 0:
        parts.append(f"{missing_count} missing")

    summary = ", ".join(parts)
    overall_healthy = error_count == 0 and missing_count == 0

    recommendations = []
    for check in checks.values():
        if check.status in (CheckStatus.ERROR, CheckStatus.MISSING) and check.fix:
            recommendations.append(check.fix)

    return DoctorReport(
        checks=checks,
        summary=summary,
        overall_healthy=overall_healthy,
        recommendations=recommendations,
    )


def format_report(report: DoctorReport) -> str:
    """Render doctor report as colored CLI output.

    Args:
        report: DoctorReport to render

    Returns:
        Formatted string with ANSI color codes
    """
    try:
        import colorama

        colorama.init()
        green = "\033[92m"
        yellow = "\033[93m"
        red = "\033[91m"
        blue = "\033[94m"
        bold = "\033[1m"
        reset = "\033[0m"
    except (ImportError, TypeError):
        green = yellow = red = blue = bold = reset = ""

    lines = [f"{bold} Browser Doctor{reset}", ""]

    lines.append(f"{bold}Environment{reset}")
    for name in ["patchright", "browser_executable", "memory", "disk", "proxy"]:
        if name in report.checks:
            check = report.checks[name]
            icon = _status_icon(check.status, green, yellow, red)
            lines.append(f"  {icon} {check.message}")
            if check.fix:
                lines.append(f"    {blue}Fix: {check.fix}{reset}")

    if "orphan_processes" in report.checks:
        lines.append("")
        lines.append(f"{bold}Process Cleanup{reset}")
        check = report.checks["orphan_processes"]
        icon = _status_icon(check.status, green, yellow, red)
        lines.append(f"  {icon} {check.message}")
        if check.fix:
            lines.append(f"    {blue}Fix: {check.fix}{reset}")

    if "browser_launch" in report.checks:
        lines.append("")
        lines.append(f"{bold}Launch Test{reset}")
        check = report.checks["browser_launch"]
        icon = _status_icon(check.status, green, yellow, red)
        lines.append(f"  {icon} {check.message}")
        if check.fix:
            lines.append(f"    {blue}Fix: {check.fix}{reset}")

    if report.recommendations:
        lines.append("")
        lines.append(f"{bold}Recommendations{reset}")
        for i, rec in enumerate(report.recommendations, 1):
            lines.append(f"  {i}. {rec}")

    lines.append("")
    if report.overall_healthy:
        lines.append(f"{green}{bold}Status: All checks passed {reset}")
    else:
        lines.append(f"{red}{bold}Status: {report.summary}{reset}")

    return "\n".join(lines)


def _status_icon(status: CheckStatus, green: str, yellow: str, red: str) -> str:
    """Get colored status icon."""
    if status == CheckStatus.OK:
        return f"{green}"
    if status == CheckStatus.WARNING:
        return f"{yellow}·"
    return f"{red}"


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
            path_part = parts[1].split()[0].strip()
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


def cleanup_orphan_processes(orphan_pids: list[int] | None = None, *, force: bool = False) -> dict[str, object]:
    """Clean up orphan chromium processes with safety checks.

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
            logger.info(f"Killed orphan chromium process: {pid}")
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


def _check_orphan_processes() -> DoctorCheckResult:
    """Check for orphan automation browser processes."""
    orphans = find_orphan_chromium_processes()

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
