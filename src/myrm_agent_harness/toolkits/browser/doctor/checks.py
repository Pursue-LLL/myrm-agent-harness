"""Browser Doctor — environment and dependency checks.

Validates dependencies, configuration, environment, and browser launchability
before actual operations, providing clear fix suggestions for each failure.

[INPUT]
- patchright (optional extra [browser]) / camoufox (stealth ladder fallback)
- ..pool.camoufox_availability::camoufox_unavailable_reason/CAMOUFOX_INSTALL_FIX (POS: non-downloading Camoufox readiness probe and its operator-facing install instructions)
- psutil (memory/disk checks)
- .launch_check::check_browser_launch (POS: bounded headless launch test)
- .orphan_check::check_orphan_processes (POS: orphan process doctor check)
- .report::CheckStatus/DoctorCheckResult/DoctorReport (POS: doctor data models)

[OUTPUT]
- run_doctor: pre-flight browser diagnostics orchestrator (synchronous quick checks + concurrent I/O-bound checks, plus host-supplied extra checks)
- check_memory/check_disk: host resource checks, shared with the runtime doctor
- _check_patchright/_check_camoufox/_check_proxy: individual checks

[POS]
Doctor core checks. Quick synchronous checks run first; I/O-bound checks
(orphan scan, host-supplied extra checks, browser launch) run concurrently via
asyncio.gather with the psutil walk offloaded to a worker thread, then results
are merged back into the ordered report. Checks that depend on a host
application (for example a server's browser extension relay) belong to that
host and are passed in as ``extra_checks``.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import inspect
import logging
import tempfile
from collections.abc import Awaitable, Mapping

from .launch_check import check_browser_launch
from .orphan_check import check_orphan_processes
from .report import CheckStatus, DoctorCheckResult, DoctorReport

logger = logging.getLogger(__name__)

_ORPHAN_CHECK = "orphan_processes"
_LAUNCH_CHECK = "browser_launch"


def _check_patchright() -> DoctorCheckResult:
    """Check if patchright is installed and get version."""
    try:
        importlib.import_module("patchright")
    except (ImportError, TypeError):
        return DoctorCheckResult(
            name="patchright",
            status=CheckStatus.ERROR,
            message="patchright not installed",
            fix="uv add patchright",
        )
    # The package has no ``__version__``, so the version comes from distribution metadata. Keep the
    # distribution name a literal here and in the camoufox check: PyInstaller's static scan only
    # bundles metadata for literal names, and the desktop backend is a frozen build. A damaged
    # dist-info yields None or raises; the report must still be produced, so both mean "unknown".
    try:
        version = importlib.metadata.version("patchright") or "unknown"
    except Exception:
        version = "unknown"
    return DoctorCheckResult(
        name="patchright",
        status=CheckStatus.OK,
        message=f"patchright {version} installed",
        details={"version": version},
    )


def _check_camoufox() -> DoctorCheckResult:
    """Check that the Camoufox browser build is installed (ladder fallback), not just the Python package."""
    from ..pool.camoufox_availability import CAMOUFOX_INSTALL_FIX, camoufox_unavailable_reason

    reason = camoufox_unavailable_reason()
    if reason is not None:
        return DoctorCheckResult(
            name="camoufox",
            status=CheckStatus.WARNING,
            message=f"camoufox not ready: {reason} (stealth auto-upgrade unavailable)",
            fix=CAMOUFOX_INSTALL_FIX,
            details={"optional": True},
        )
    try:
        version = importlib.metadata.version("camoufox") or "unknown"
    except Exception:
        version = "unknown"
    return DoctorCheckResult(
        name="camoufox",
        status=CheckStatus.OK,
        message=f"camoufox {version} installed",
        details={"version": version},
    )


def check_memory() -> DoctorCheckResult:
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

    try:
        memory = psutil.virtual_memory()
        available_gb = memory.available / (1024**3)
        total_gb = memory.total / (1024**3)
        used_percent = memory.percent
    except Exception as exc:
        return DoctorCheckResult(
            name="memory",
            status=CheckStatus.WARNING,
            message=f"Cannot check memory: {exc}",
        )

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
        details={
            "available_gb": round(available_gb, 2),
            "total_gb": round(total_gb, 2),
            "used_percent": used_percent,
        },
    )


def check_disk() -> DoctorCheckResult:
    """Check free space on the volume that holds the browser's temporary files."""
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
        # The runtime writes under the platform temp directory; a fixed Unix path does not exist on Windows.
        usage = psutil.disk_usage(tempfile.gettempdir())
        available_gb = usage.free / (1024**3)
        used_percent = usage.percent

        if available_gb < 0.5:
            return DoctorCheckResult(
                name="disk",
                status=CheckStatus.ERROR,
                message=f"Low disk space: {available_gb:.1f} GB available ({used_percent:.0f}% used)",
                fix="Free up disk space or clean up temporary files",
                details={
                    "available_gb": round(available_gb, 2),
                    "used_percent": used_percent,
                },
            )

        if available_gb < 1.0:
            return DoctorCheckResult(
                name="disk",
                status=CheckStatus.WARNING,
                message=f"Disk space tight: {available_gb:.1f} GB available ({used_percent:.0f}% used)",
                fix="Consider freeing up disk space for better stability",
                details={
                    "available_gb": round(available_gb, 2),
                    "used_percent": used_percent,
                },
            )

        return DoctorCheckResult(
            name="disk",
            status=CheckStatus.OK,
            message=f"Disk space: {available_gb:.1f} GB available ({used_percent:.0f}% used)",
            details={
                "available_gb": round(available_gb, 2),
                "used_percent": used_percent,
            },
        )
    except Exception as exc:
        return DoctorCheckResult(
            name="disk",
            status=CheckStatus.WARNING,
            message=f"Cannot check disk space: {exc}",
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


async def _run_extra_check(name: str, check: Awaitable[DoctorCheckResult]) -> DoctorCheckResult:
    """Await a host-supplied check; a crash becomes one warning row instead of sinking the whole report."""
    try:
        return await check
    except Exception as exc:
        logger.warning("Doctor extra check %s raised", name, exc_info=True)
        return DoctorCheckResult(
            name=name,
            status=CheckStatus.WARNING,
            message=f"Check could not run: {exc}",
            fix="Check the application logs for the failure details",
        )


def _discard_unawaited(checks: Mapping[str, Awaitable[DoctorCheckResult]]) -> None:
    """Close rejected checks that will never be awaited so they leave no "never awaited" warning."""
    for check in checks.values():
        if inspect.iscoroutine(check):
            check.close()


async def run_doctor(
    *,
    include_launch_test: bool = True,
    include_orphan_check: bool = True,
    launch_options: dict[str, object] | None = None,
    browser_proxy: str = "",
    extra_checks: Mapping[str, Awaitable[DoctorCheckResult]] | None = None,
) -> DoctorReport:
    """Run comprehensive browser diagnostics.

    Args:
        include_launch_test: Whether to test actual browser launch
        include_orphan_check: Whether to check for orphan processes
        launch_options: Optional custom launch options for launch test
        browser_proxy: Comma-separated proxy URLs to report in the proxy check
        extra_checks: Host-specific checks keyed by report name. They run concurrently with the
            built-in I/O-bound checks and count in the summary like any other check. A name that
            collides with a built-in check raises ``ValueError``; a check that raises is reported as a
            warning row. ``format_report`` renders only the built-in sections.

    Returns:
        DoctorReport with all check results and recommendations
    """
    checks: dict[str, DoctorCheckResult] = {}

    checks["patchright"] = _check_patchright()
    checks["camoufox"] = _check_camoufox()
    checks["memory"] = check_memory()
    checks["disk"] = check_disk()
    checks["proxy"] = _check_proxy(browser_proxy)

    extra = dict(extra_checks or {})
    if shadowed := sorted(extra.keys() & {*checks, _ORPHAN_CHECK, _LAUNCH_CHECK}):
        _discard_unawaited(extra)
        raise ValueError(f"extra_checks may not reuse built-in check names: {', '.join(shadowed)}")

    # I/O-bound checks run concurrently; the orphan scan is offloaded to a worker
    # thread so the psutil walk never blocks the event loop.
    pending: dict[str, Awaitable[DoctorCheckResult]] = {}
    if include_orphan_check:
        pending[_ORPHAN_CHECK] = asyncio.to_thread(check_orphan_processes)
    pending.update({name: _run_extra_check(name, check) for name, check in extra.items()})
    if include_launch_test:
        pending[_LAUNCH_CHECK] = check_browser_launch(launch_options)

    results = await asyncio.gather(*pending.values())
    checks.update(zip(pending, results, strict=True))

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
