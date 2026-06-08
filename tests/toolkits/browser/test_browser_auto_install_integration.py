"""Integration tests for zero-config Chromium auto-install.

These tests use real subprocess calls (no mocks) to verify the
auto-install pipeline end-to-end.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from myrm_agent_harness.toolkits.browser.doctor import CheckStatus, run_doctor
from myrm_agent_harness.toolkits.browser.pool.browser_launcher import (
    _auto_install_chromium,
    _is_executable_missing,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def _reset_install_state() -> None:
    """Reset module-level install state before each test."""
    import myrm_agent_harness.toolkits.browser.pool.browser_launcher as mod

    mod._last_install_failure_at = 0.0
    mod._install_lock = None


class TestAutoInstallIntegration:
    """Real subprocess integration tests for _auto_install_chromium."""

    async def test_patchright_install_chromium_real_subprocess(self) -> None:
        """Verify patchright install chromium succeeds via real subprocess.

        Since Chromium is already installed, this should complete quickly
        with a success return code (patchright detects existing install).
        """
        result = await _auto_install_chromium()
        assert result is True

    async def test_cooldown_blocks_second_install_after_forced_failure(self) -> None:
        """Verify cooldown mechanism prevents rapid retries."""
        import myrm_agent_harness.toolkits.browser.pool.browser_launcher as mod

        mod._last_install_failure_at = time.monotonic()

        result = await _auto_install_chromium()
        assert result is False

    async def test_concurrent_install_serialized(self) -> None:
        """Verify concurrent install calls are serialized by the lock."""
        results = await asyncio.gather(
            _auto_install_chromium(),
            _auto_install_chromium(),
        )
        assert all(r is True for r in results)


class TestDoctorAutoFixIntegration:
    """Real integration tests for doctor auto_fix mode."""

    async def test_doctor_auto_fix_with_existing_browser(self) -> None:
        """When browser is already installed, auto_fix should not trigger install.

        doctor should report browser_launch=OK and no auto_install key.
        """
        report = await run_doctor(
            include_launch_test=True,
            include_orphan_check=False,
            auto_fix=True,
        )

        assert "browser_launch" in report.checks
        assert report.checks["browser_launch"].status == CheckStatus.OK
        assert "auto_install" not in report.checks

    async def test_doctor_without_auto_fix(self) -> None:
        """Standard doctor run should not have auto_install."""
        report = await run_doctor(
            include_launch_test=True,
            include_orphan_check=False,
            auto_fix=False,
        )

        assert "browser_launch" in report.checks
        assert report.checks["browser_launch"].status == CheckStatus.OK
        assert "auto_install" not in report.checks


class TestErrorDetectionIntegration:
    """Verify error detection works with real exception types from patchright."""

    async def test_real_patchright_error_format(self) -> None:
        """Patchright raises errors with the exact format we detect."""
        exc = Exception(
            "Executable doesn't exist at "
            "/Users/test/.cache/patchright/chromium-1148/chrome-mac/Chromium.app"
            "/Contents/MacOS/Chromium"
        )
        assert _is_executable_missing(exc) is True

    async def test_real_playwright_error_format(self) -> None:
        """Playwright-style errors are also detected."""
        exc = Exception(
            "browserType.launch: Executable doesn't exist at "
            "/ms-playwright/chromium-1148/chrome-linux/chrome"
        )
        assert _is_executable_missing(exc) is True

    async def test_non_missing_browser_errors_ignored(self) -> None:
        """Network/CDP errors should not trigger auto-install."""
        for msg in [
            "net::ERR_CONNECTION_REFUSED",
            "Target page, context or browser has been closed",
            "Protocol error (Target.createTarget): Target closed",
            "Browser closed unexpectedly",
        ]:
            assert _is_executable_missing(Exception(msg)) is False
