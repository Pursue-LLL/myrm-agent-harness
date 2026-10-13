"""Browser Doctor — headless launch test.

Starts a headless browser, opens a blank page and reports the outcome, with an
operator-facing fix for each failure class.

[INPUT]
- patchright (optional extra [browser]): imported lazily so a missing package is reported instead of raised
- ..process_owner::owner_stamp_env (POS: ownership stamp naming the launching process)
- ..utils::is_timeout_error (POS: builtin/patchright timeout detection)
- .report::CheckStatus/DoctorCheckResult (POS: doctor data models)

[OUTPUT]
- check_browser_launch: bounded browser launch test returning a DoctorCheckResult

[POS]
Doctor launch test. Kept apart from the static environment checks because it is
the only check that starts a browser process, and it carries its own timeout.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

from ..process_owner import owner_stamp_env
from ..utils import is_timeout_error
from .report import CheckStatus, DoctorCheckResult

if TYPE_CHECKING:
    from patchright.async_api._context_manager import PlaywrightContextManager

_LAUNCH_TIMEOUT_S = 20.0


async def _probe_browser_launch(
    launch_opts: dict[str, object],
    async_playwright: Callable[[], PlaywrightContextManager],
) -> DoctorCheckResult:
    """Launch a headless browser and probe basic page functionality.

    Releases the playwright connection on every exit path so a cancelled probe
    (e.g. the enclosing timeout) never leaks browser processes.
    """
    playwright = await async_playwright().start()
    try:
        # The probe browser carries the ownership stamp so a leftover of this probe is recognisable; an env
        # the caller supplied is theirs to define. Playwright validates the option keys at launch time.
        browser_opts = {"env": {**os.environ, **owner_stamp_env()}, **launch_opts}
        browser = await playwright.chromium.launch(**browser_opts)  # type: ignore[arg-type]
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


async def check_browser_launch(
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

    default_args = ["--no-sandbox", "--disable-dev-shm-usage"]
    if sys.platform == "darwin":
        default_args.append("--disable-features=MacAppCodeSignClone")

    launch_opts = launch_options or {
        "headless": True,
        "args": default_args,
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
                message=f"Browser launch timed out after {_LAUNCH_TIMEOUT_S:.0f}s",
                fix="Check system resources or network connectivity",
            )

        error_msg = str(exc).lower()

        if "executable doesn't exist" in error_msg or "not found" in error_msg:
            return DoctorCheckResult(
                name="browser_launch",
                status=CheckStatus.ERROR,
                message=f"Browser executable not found: {exc}",
                fix="Run 'patchright install chromium' to install the bundled browser",
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
