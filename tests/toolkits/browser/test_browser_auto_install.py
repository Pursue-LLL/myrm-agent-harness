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
from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine, LaunchMode


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

    def test_empty_error_message(self) -> None:
        assert _is_executable_missing(Exception("")) is False

    def test_none_converted_to_str(self) -> None:
        assert _is_executable_missing(Exception(None)) is False

    def test_real_patchright_path_format(self) -> None:
        exc = Exception(
            "Executable doesn't exist at "
            "/Users/test/.cache/patchright/chromium-1148/chrome-mac/Chromium.app"
            "/Contents/MacOS/Chromium"
        )
        assert _is_executable_missing(exc) is True

    def test_real_linux_path_format(self) -> None:
        exc = Exception(
            "browserType.launch: Executable doesn't exist at "
            "/ms-playwright/chromium-1148/chrome-linux/chrome"
        )
        assert _is_executable_missing(exc) is True

    def test_browser_closed_not_missing(self) -> None:
        assert _is_executable_missing(Exception("Browser closed unexpectedly")) is False

    def test_protocol_error_not_missing(self) -> None:
        assert _is_executable_missing(Exception("Protocol error (Target.createTarget)")) is False

    def test_net_err_not_missing(self) -> None:
        assert _is_executable_missing(Exception("net::ERR_CONNECTION_REFUSED")) is False


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

    def test_empty_error_message(self) -> None:
        msg = _build_install_failure_message(Exception(""))
        assert "patchright install chromium" in msg
        assert "automatic installation failed" in msg.lower()

    def test_multiline_error_preserved(self) -> None:
        exc = Exception("line1\nline2\nline3")
        msg = _build_install_failure_message(exc)
        assert "line1" in msg


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

    @pytest.mark.asyncio
    async def test_generic_exception_sets_cooldown(self) -> None:
        """Covers the catch-all Exception handler in _auto_install_chromium."""
        import myrm_agent_harness.toolkits.browser.pool.browser_launcher as mod

        with patch("asyncio.create_subprocess_exec", side_effect=PermissionError("denied")):
            result = await _auto_install_chromium()

        assert result is False
        assert mod._last_install_failure_at > 0

    @pytest.mark.asyncio
    async def test_double_check_after_lock_with_concurrent_cooldown(self) -> None:
        """Verify the double-check pattern: if cooldown is set while waiting for lock."""
        import myrm_agent_harness.toolkits.browser.pool.browser_launcher as mod

        mod._install_lock = asyncio.Lock()

        async with mod._install_lock:
            mod._last_install_failure_at = time.monotonic()

            async def attempt_install() -> bool:
                return await _auto_install_chromium()

            task = asyncio.create_task(attempt_install())
            await asyncio.sleep(0.01)

        result = await task
        assert result is False

    @pytest.mark.asyncio
    async def test_lazy_lock_initialization(self) -> None:
        """Verify lock is created on first call, not at import time."""
        import myrm_agent_harness.toolkits.browser.pool.browser_launcher as mod

        assert mod._install_lock is None

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"OK", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await _auto_install_chromium()

        assert mod._install_lock is not None
        assert isinstance(mod._install_lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_stderr_truncation_on_failure(self) -> None:
        """Verify long stderr output doesn't cause issues."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"X" * 2000))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await _auto_install_chromium()
        assert result is False


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

    @pytest.mark.asyncio
    async def test_auto_install_only_attempted_once(self) -> None:
        """Even if executable still missing after install, auto_installed guard prevents retry."""
        launcher = BrowserLauncher(
            launch_options={"headless": True},
            launch_mode=LaunchMode.LAUNCH,
        )

        mock_pw = MagicMock()
        mock_pw.chromium.launch = AsyncMock(
            side_effect=Exception("Executable doesn't exist at /path/chromium")
        )
        mock_pw.stop = AsyncMock()

        install_call_count = 0
        mock_install_proc = AsyncMock()
        mock_install_proc.returncode = 0
        mock_install_proc.communicate = AsyncMock(return_value=(b"OK", b""))

        original_create = asyncio.create_subprocess_exec

        async def count_installs(*args: object, **kwargs: object) -> AsyncMock:
            nonlocal install_call_count
            install_call_count += 1
            return mock_install_proc

        with (
            patch.object(launcher, "_ensure_playwright", return_value=mock_pw),
            patch("asyncio.create_subprocess_exec", side_effect=count_installs),
        ):
            with pytest.raises(BrowserLaunchError):
                await launcher._launch_new_browser()

        assert install_call_count == 1

    @pytest.mark.asyncio
    async def test_playwright_reset_after_install(self) -> None:
        """Verify playwright is stopped and reset after successful install."""
        launcher = BrowserLauncher(
            launch_options={"headless": True},
            launch_mode=LaunchMode.LAUNCH,
        )

        call_count = 0
        mock_browser = MagicMock()
        mock_browser._impl_obj = MagicMock(_process=MagicMock(pid=99))

        async def mock_launch(**kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Executable doesn't exist at /path")
            return mock_browser

        mock_pw = MagicMock()
        mock_pw.chromium.launch = mock_launch
        mock_pw.stop = AsyncMock()

        launcher._playwright = mock_pw

        mock_install_proc = AsyncMock()
        mock_install_proc.returncode = 0
        mock_install_proc.communicate = AsyncMock(return_value=(b"OK", b""))

        with (
            patch.object(launcher, "_ensure_playwright", return_value=mock_pw),
            patch("asyncio.create_subprocess_exec", return_value=mock_install_proc),
        ):
            await launcher._launch_new_browser()

        mock_pw.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_missing_error_no_auto_install(self) -> None:
        """Timeout/connection errors should NOT trigger auto-install."""
        launcher = BrowserLauncher(
            launch_options={"headless": True},
            launch_mode=LaunchMode.LAUNCH,
        )

        mock_pw = MagicMock()
        mock_pw.chromium.launch = AsyncMock(side_effect=TimeoutError("browser timeout"))

        with patch.object(launcher, "_ensure_playwright", return_value=mock_pw):
            with pytest.raises(BrowserLaunchError, match="Failed to create Browser"):
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

    @pytest.mark.asyncio
    async def test_auto_fix_skipped_for_non_executable_error(self) -> None:
        """auto_fix should NOT trigger if launch error is not about missing executable."""
        from myrm_agent_harness.toolkits.browser.doctor import CheckStatus, run_doctor

        with patch(
            "myrm_agent_harness.toolkits.browser.doctor._check_browser_launch",
            return_value=MagicMock(
                name="browser_launch",
                status=CheckStatus.ERROR,
                message="Connection refused",
                fix="Check if browser is running",
                details=None,
            ),
        ):
            report = await run_doctor(
                include_launch_test=True,
                include_orphan_check=False,
                auto_fix=True,
            )

        assert "auto_install" not in report.checks
        assert report.checks["browser_launch"].status == CheckStatus.ERROR

    @pytest.mark.asyncio
    async def test_auto_fix_install_fails(self) -> None:
        """auto_fix triggers install but install fails — should report error."""
        from myrm_agent_harness.toolkits.browser.doctor import CheckStatus, run_doctor

        mock_install_proc = AsyncMock()
        mock_install_proc.returncode = 1
        mock_install_proc.communicate = AsyncMock(return_value=(b"", b"disk full"))

        with (
            patch(
                "myrm_agent_harness.toolkits.browser.doctor._check_browser_launch",
                return_value=MagicMock(
                    name="browser_launch",
                    status=CheckStatus.ERROR,
                    message="Browser executable not found",
                    fix="Run 'patchright install chromium' or check BROWSER_EXECUTABLE_PATH",
                    details=None,
                ),
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
        assert report.checks["auto_install"].status == CheckStatus.ERROR

    @pytest.mark.asyncio
    async def test_auto_fix_patchright_cli_not_found(self) -> None:
        """auto_fix when patchright CLI is not on PATH."""
        from myrm_agent_harness.toolkits.browser.doctor import CheckStatus, run_doctor

        with (
            patch(
                "myrm_agent_harness.toolkits.browser.doctor._check_browser_launch",
                return_value=MagicMock(
                    name="browser_launch",
                    status=CheckStatus.ERROR,
                    message="Browser executable not found",
                    fix="Run 'patchright install chromium' or check BROWSER_EXECUTABLE_PATH",
                    details=None,
                ),
            ),
            patch("shutil.which", return_value=None),
        ):
            report = await run_doctor(
                include_launch_test=True,
                include_orphan_check=False,
                auto_fix=True,
            )

        assert "auto_install" in report.checks
        assert report.checks["auto_install"].status == CheckStatus.ERROR
        assert "not found" in report.checks["auto_install"].message.lower()

    @pytest.mark.asyncio
    async def test_auto_fix_install_timeout(self) -> None:
        """auto_fix install times out."""
        from myrm_agent_harness.toolkits.browser.doctor import CheckStatus, run_doctor

        with (
            patch(
                "myrm_agent_harness.toolkits.browser.doctor._check_browser_launch",
                return_value=MagicMock(
                    name="browser_launch",
                    status=CheckStatus.ERROR,
                    message="Browser executable not found",
                    fix="Run 'patchright install chromium' or check BROWSER_EXECUTABLE_PATH",
                    details=None,
                ),
            ),
            patch("shutil.which", return_value="/usr/bin/patchright"),
            patch("asyncio.create_subprocess_exec", side_effect=TimeoutError),
        ):
            report = await run_doctor(
                include_launch_test=True,
                include_orphan_check=False,
                auto_fix=True,
            )

        assert "auto_install" in report.checks
        assert report.checks["auto_install"].status == CheckStatus.ERROR
        assert "timed out" in report.checks["auto_install"].message.lower()

    @pytest.mark.asyncio
    async def test_auto_fix_install_generic_exception(self) -> None:
        """auto_fix catches unexpected exceptions gracefully."""
        from myrm_agent_harness.toolkits.browser.doctor import CheckStatus, run_doctor

        with (
            patch(
                "myrm_agent_harness.toolkits.browser.doctor._check_browser_launch",
                return_value=MagicMock(
                    name="browser_launch",
                    status=CheckStatus.ERROR,
                    message="Browser executable not found",
                    fix="Run 'patchright install chromium' or check BROWSER_EXECUTABLE_PATH",
                    details=None,
                ),
            ),
            patch("shutil.which", return_value="/usr/bin/patchright"),
            patch("asyncio.create_subprocess_exec", side_effect=OSError("weird error")),
        ):
            report = await run_doctor(
                include_launch_test=True,
                include_orphan_check=False,
                auto_fix=True,
            )

        assert "auto_install" in report.checks
        assert report.checks["auto_install"].status == CheckStatus.ERROR

    @pytest.mark.asyncio
    async def test_auto_fix_false_does_not_trigger_install(self) -> None:
        """Explicit auto_fix=False should never trigger install even if executable is missing."""
        from myrm_agent_harness.toolkits.browser.doctor import CheckStatus, run_doctor

        with patch(
            "myrm_agent_harness.toolkits.browser.doctor._check_browser_launch",
            return_value=MagicMock(
                name="browser_launch",
                status=CheckStatus.ERROR,
                message="Browser executable not found",
                fix="Run 'patchright install chromium' or check BROWSER_EXECUTABLE_PATH",
                details=None,
            ),
        ):
            report = await run_doctor(
                include_launch_test=True,
                include_orphan_check=False,
                auto_fix=False,
            )

        assert "auto_install" not in report.checks
        assert report.checks["browser_launch"].status == CheckStatus.ERROR
