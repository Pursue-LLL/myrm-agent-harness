"""Unit tests for zero-config Chromium auto-install in BrowserLauncher and Doctor."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.exceptions import BrowserLaunchError
from myrm_agent_harness.toolkits.browser.pool.browser_launcher import (
    BrowserLauncher,
    _auto_install_chromium,
    _build_install_failure_message,
    _is_executable_missing,
)
from myrm_agent_harness.toolkits.browser.pool.config import LaunchMode


# ---------------------------------------------------------------------------
# _is_executable_missing
# ---------------------------------------------------------------------------


class TestIsExecutableMissing:
    def test_detects_patchright_error(self) -> None:
        exc = Exception("Executable doesn't exist at /path/to/chromium")
        assert _is_executable_missing(exc) is True

    def test_detects_no_such_file(self) -> None:
        exc = Exception("No such file or directory: '/usr/bin/chromium'")
        assert _is_executable_missing(exc) is True

    def test_ignores_timeout_error(self) -> None:
        exc = Exception("Timeout while waiting for browser")
        assert _is_executable_missing(exc) is False

    def test_ignores_connection_error(self) -> None:
        exc = Exception("Connection refused to CDP endpoint")
        assert _is_executable_missing(exc) is False

    def test_case_insensitive(self) -> None:
        exc = Exception("EXECUTABLE DOESN'T EXIST")
        assert _is_executable_missing(exc) is True


# ---------------------------------------------------------------------------
# _build_install_failure_message
# ---------------------------------------------------------------------------


class TestBuildInstallFailureMessage:
    def test_contains_manual_fix_command(self) -> None:
        msg = _build_install_failure_message(Exception("test"))
        assert "patchright install chromium" in msg

    def test_contains_common_causes(self) -> None:
        msg = _build_install_failure_message(Exception("test"))
        assert "disk space" in msg.lower()
        assert "internet" in msg.lower() or "network" in msg.lower()
        assert "permission" in msg.lower()

    def test_contains_original_error(self) -> None:
        msg = _build_install_failure_message(Exception("specific error detail"))
        assert "specific error detail" in msg


# ---------------------------------------------------------------------------
# _auto_install_chromium
# ---------------------------------------------------------------------------


class TestAutoInstallChromium:
    @pytest.fixture(autouse=True)
    def _reset_module_state(self) -> None:
        """Reset module-level state before each test."""
        import myrm_agent_harness.toolkits.browser.pool.browser_launcher as mod

        mod._last_install_failure_at = 0.0
        mod._install_lock = None

    @pytest.mark.asyncio
    async def test_successful_install(self) -> None:
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"Installed", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await _auto_install_chromium()
        assert result is True

    @pytest.mark.asyncio
    async def test_failed_install_sets_cooldown(self) -> None:
        import myrm_agent_harness.toolkits.browser.pool.browser_launcher as mod

        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"Error"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await _auto_install_chromium()

        assert result is False
        assert mod._last_install_failure_at > 0

    @pytest.mark.asyncio
    async def test_cooldown_prevents_retry(self) -> None:
        import myrm_agent_harness.toolkits.browser.pool.browser_launcher as mod

        mod._last_install_failure_at = time.monotonic()

        result = await _auto_install_chromium()
        assert result is False

    @pytest.mark.asyncio
    async def test_patchright_cli_not_found(self) -> None:
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            result = await _auto_install_chromium()
        assert result is False

    @pytest.mark.asyncio
    async def test_timeout_sets_cooldown(self) -> None:
        import myrm_agent_harness.toolkits.browser.pool.browser_launcher as mod

        with patch("asyncio.create_subprocess_exec", side_effect=TimeoutError):
            result = await _auto_install_chromium()

        assert result is False
        assert mod._last_install_failure_at > 0

    @pytest.mark.asyncio
    async def test_successful_install_resets_cooldown(self) -> None:
        import myrm_agent_harness.toolkits.browser.pool.browser_launcher as mod

        mod._last_install_failure_at = time.monotonic() - 2000

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"Installed", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await _auto_install_chromium()

        assert result is True
        assert mod._last_install_failure_at == 0.0


# ---------------------------------------------------------------------------
# BrowserLauncher._launch_new_browser auto-install integration
# ---------------------------------------------------------------------------


class TestLaunchNewBrowserAutoInstall:
    @pytest.fixture(autouse=True)
    def _reset_module_state(self) -> None:
        import myrm_agent_harness.toolkits.browser.pool.browser_launcher as mod

        mod._last_install_failure_at = 0.0
        mod._install_lock = None

    @pytest.mark.asyncio
    async def test_auto_installs_on_missing_executable(self) -> None:
        launcher = BrowserLauncher(
            launch_options={"headless": True},
            launch_mode=LaunchMode.LAUNCH,
        )

        call_count = 0
        mock_browser = MagicMock()
        mock_browser._impl_obj = MagicMock(_process=MagicMock(pid=12345))

        async def mock_launch(**kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Executable doesn't exist at /path/chromium")
            return mock_browser

        mock_pw = MagicMock()
        mock_pw.chromium.launch = mock_launch

        mock_install_proc = AsyncMock()
        mock_install_proc.returncode = 0
        mock_install_proc.communicate = AsyncMock(return_value=(b"OK", b""))

        with (
            patch.object(launcher, "_ensure_playwright", return_value=mock_pw),
            patch("asyncio.create_subprocess_exec", return_value=mock_install_proc),
        ):
            inst = await launcher._launch_new_browser()

        assert inst is not None
        assert call_count == 2  # First failed, second succeeded after install

    @pytest.mark.asyncio
    async def test_no_auto_install_for_camoufox(self) -> None:
        from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine

        launcher = BrowserLauncher(
            launch_options={"headless": True},
            launch_mode=LaunchMode.LAUNCH,
            engine=BrowserEngine.FIREFOX_CAMOUFOX,
        )

        with pytest.raises(BrowserLaunchError, match="camoufox is not installed"):
            await launcher._launch_new_browser()

    @pytest.mark.asyncio
    async def test_friendly_error_on_install_failure(self) -> None:
        launcher = BrowserLauncher(
            launch_options={"headless": True},
            launch_mode=LaunchMode.LAUNCH,
        )

        mock_pw = MagicMock()
        mock_pw.chromium.launch = AsyncMock(
            side_effect=Exception("Executable doesn't exist at /path/chromium")
        )
        mock_pw.stop = AsyncMock()

        mock_install_proc = AsyncMock()
        mock_install_proc.returncode = 1
        mock_install_proc.communicate = AsyncMock(return_value=(b"", b"Network error"))

        with (
            patch.object(launcher, "_ensure_playwright", return_value=mock_pw),
            patch("asyncio.create_subprocess_exec", return_value=mock_install_proc),
        ):
            with pytest.raises(BrowserLaunchError, match="automatic installation failed"):
                await launcher._launch_new_browser()


# ---------------------------------------------------------------------------
# Doctor auto_fix
# ---------------------------------------------------------------------------


class TestDoctorAutoFix:
    @pytest.mark.asyncio
    async def test_run_doctor_without_auto_fix(self) -> None:
        from myrm_agent_harness.toolkits.browser.doctor import run_doctor

        report = await run_doctor(include_launch_test=False, include_orphan_check=False)
        assert "auto_install" not in report.checks

    @pytest.mark.asyncio
    async def test_run_doctor_auto_fix_triggers_install(self) -> None:
        from myrm_agent_harness.toolkits.browser.doctor import CheckStatus, run_doctor

        mock_install_proc = AsyncMock()
        mock_install_proc.returncode = 0
        mock_install_proc.communicate = AsyncMock(return_value=(b"Installed", b""))

        with (
            patch(
                "myrm_agent_harness.toolkits.browser.doctor._check_browser_launch",
                side_effect=[
                    MagicMock(
                        name="browser_launch",
                        status=CheckStatus.ERROR,
                        message="Browser executable not found",
                        fix="Run 'patchright install chromium' or check BROWSER_EXECUTABLE_PATH",
                        details=None,
                    ),
                    MagicMock(
                        name="browser_launch",
                        status=CheckStatus.OK,
                        message="Browser launch test successful",
                        fix=None,
                        details=None,
                    ),
                ],
            ),
            patch("shutil.which", return_value="/usr/bin/patchright"),
            patch("asyncio.create_subprocess_exec", return_value=mock_install_proc),
        ):
            report = await run_doctor(
                include_launch_test=True,
                include_orphan_check=False,
                auto_fix=True,
            )

        assert "auto_install" in report.checks
        assert report.checks["auto_install"].status == CheckStatus.OK
