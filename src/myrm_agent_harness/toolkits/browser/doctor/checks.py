"""Browser Doctor — environment and dependency checks.

Validates dependencies, configuration, environment, and browser launchability
before actual operations, providing clear fix suggestions for each failure.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from myrm_agent_harness.infra.tls_compat import create_httpx_client

from ..utils import is_timeout_error
from .orphans import check_orphan_processes
from .report import CheckStatus, DoctorCheckResult, DoctorReport

logger = logging.getLogger(__name__)


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


def _check_camoufox() -> DoctorCheckResult:
    """Check if camoufox is installed (stealth ladder fallback)."""
    try:
        import camoufox

        version = getattr(camoufox, "__version__", "unknown")
        return DoctorCheckResult(
            name="camoufox",
            status=CheckStatus.OK,
            message=f"camoufox {version} installed",
            details={"version": version},
        )
    except (ImportError, TypeError):
        return DoctorCheckResult(
            name="camoufox",
            status=CheckStatus.WARNING,
            message="camoufox not installed (stealth auto-upgrade unavailable)",
            fix="uv add 'camoufox>=0.4.11' or pip install 'myrm-agent-harness[browser]'",
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

    try:
        path_exists = executable_path.exists()
        path_executable = os.access(executable_path, os.X_OK)
    except Exception as exc:
        return DoctorCheckResult(
            name="browser_executable",
            status=CheckStatus.WARNING,
            message=f"Cannot check browser executable: {exc}",
            details={"path": str(executable_path)},
        )

    if not path_exists:
        return DoctorCheckResult(
            name="browser_executable",
            status=CheckStatus.ERROR,
            message=f"Browser executable not found: {executable_path}",
            fix=f"Remove invalid BROWSER_EXECUTABLE_PATH or install browser at {executable_path}",
            details={"path": str(executable_path), "exists": False},
        )

    if not path_executable:
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
                fix="Consider cleaning up /tmp for better stability",
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


_LAUNCH_TIMEOUT_S = 20.0


async def _probe_browser_launch(
    launch_opts: dict[str, object],
    async_playwright: Callable[..., Any],
) -> DoctorCheckResult:
    """Launch a headless browser and probe basic page functionality.

    Releases the playwright connection on every exit path so a cancelled probe
    (e.g. the enclosing timeout) never leaks browser processes.
    """
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
                    details={
                        "headless": launch_opts.get("headless"),
                        "title": title,
                    },
                )
            finally:
                await context.close()
        finally:
            await browser.close()
    finally:
        await playwright.stop()


async def _check_browser_launch(
    launch_options: dict[str, object] | None = None,
) -> DoctorCheckResult:
    """Test browser launch and basic functionality within a bounded timeout."""
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
        return await asyncio.wait_for(
            _probe_browser_launch(launch_opts, async_playwright),
            timeout=_LAUNCH_TIMEOUT_S,
        )
    except Exception as exc:
        if is_timeout_error(exc):
            return DoctorCheckResult(
                name="browser_launch",
                status=CheckStatus.ERROR,
                message=f"Browser launch timeout: {exc}",
                fix="Check system resources or network connectivity",
            )

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


async def _check_extension_relay() -> DoctorCheckResult:
    """Probe server extension setup hints for CDP relay readiness."""
    import json

    import httpx

    base = os.environ.get("MYRM_SERVER_URL", "http://127.0.0.1:8080").rstrip("/")
    url = f"{base}/api/v1/extension/setup-hints"
    if not url.startswith(("http://", "https://")):
        return DoctorCheckResult(
            name="extension_relay",
            status=CheckStatus.WARNING,
            message="MYRM_SERVER_URL must use http(s) scheme",
            fix="Set MYRM_SERVER_URL to an http(s) endpoint",
        )
    try:
        async with create_httpx_client(timeout=2.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = json.loads(response.text)
    except (httpx.HTTPError, OSError):
        return DoctorCheckResult(
            name="extension_relay",
            status=CheckStatus.WARNING,
            message="Server unreachable; cannot verify browser extension CDP relay",
            fix="Start myrm-agent-server and connect the browser extension from WebUI",
        )
    except Exception as exc:
        return DoctorCheckResult(
            name="extension_relay",
            status=CheckStatus.WARNING,
            message=f"Extension relay probe failed: {exc}",
            fix="Check server logs and extension connection settings",
        )

    if payload.get("relay_cdp_ready") is True and payload.get("access_policy_valid") is True:
        return DoctorCheckResult(
            name="extension_relay",
            status=CheckStatus.OK,
            message="Extension CDP relay is ready for login-state automation",
        )

    if payload.get("relay_cdp_ready") is True and not payload.get("access_policy_valid"):
        return DoctorCheckResult(
            name="extension_relay",
            status=CheckStatus.WARNING,
            message="Extension relay is up but access policy is not configured",
            fix=("Add authorized domains or enable allow-all in Settings → Browser Extension"),
        )

    if payload.get("auth_token_required") and not payload.get("auth_token_configured"):
        return DoctorCheckResult(
            name="extension_relay",
            status=CheckStatus.WARNING,
            message="Extension auth token missing on server",
            fix="Set EXTENSION_AUTH_TOKEN on the server, then pair the extension from WebUI",
        )

    return DoctorCheckResult(
        name="extension_relay",
        status=CheckStatus.WARNING,
        message="Browser extension is not connected or CDP relay is not ready",
        fix="Install the MV3 extension, generate a pairing code in WebUI, and connect",
    )


async def run_doctor(
    *,
    include_launch_test: bool = True,
    include_orphan_check: bool = True,
    launch_options: dict[str, object] | None = None,
    browser_executable_path: str = "",
    browser_proxy: str = "",
) -> DoctorReport:
    """Run comprehensive browser diagnostics.

    Args:
        include_launch_test: Whether to test actual browser launch
        include_orphan_check: Whether to check for orphan processes
        launch_options: Optional custom launch options for launch test
        browser_executable_path: Custom browser executable path to check
        browser_proxy: Proxy URL to validate

    Returns:
        DoctorReport with all check results and recommendations
    """
    checks: dict[str, DoctorCheckResult] = {}

    checks["patchright"] = _check_patchright()
    checks["camoufox"] = _check_camoufox()
    checks["browser_executable"] = _check_browser_executable(browser_executable_path)
    checks["memory"] = _check_memory()
    checks["disk"] = _check_disk()
    checks["proxy"] = _check_proxy(browser_proxy)

    # I/O-bound checks run concurrently; the orphan scan is offloaded to a worker
    # thread so the psutil walk never blocks the event loop.
    pending: dict[str, Awaitable[DoctorCheckResult]] = {}
    if include_orphan_check:
        pending["orphan_processes"] = asyncio.to_thread(check_orphan_processes)
    pending["extension_relay"] = _check_extension_relay()
    if include_launch_test:
        pending["browser_launch"] = _check_browser_launch(launch_options)

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
