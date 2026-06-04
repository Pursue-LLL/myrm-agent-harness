"""Tests for window_text() — WindowTextResult types and backend implementations.

Covers:
- WindowTextResult dataclass: fields, defaults, frozen immutability
- _extract_window_text (macOS): success, permission error, timeout, parse edge cases
- LinuxBackend.window_text: xdotool/xprop integration
- Protocol compliance: both backends satisfy ComputerBackend.window_text()
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.types import WindowTextResult


class TestWindowTextResult:
    """WindowTextResult dataclass behaviour."""

    def test_default_values(self) -> None:
        r = WindowTextResult()
        assert r.window_title == ""
        assert r.app_name == ""
        assert r.text == ""
        assert r.success is True
        assert r.needs_permission is False

    def test_custom_values(self) -> None:
        r = WindowTextResult(
            window_title="Google",
            app_name="Chrome",
            text="Hello World",
            success=True,
            needs_permission=False,
        )
        assert r.window_title == "Google"
        assert r.app_name == "Chrome"
        assert r.text == "Hello World"

    def test_permission_failure(self) -> None:
        r = WindowTextResult(success=False, needs_permission=True, app_name="Finder")
        assert r.success is False
        assert r.needs_permission is True
        assert r.app_name == "Finder"

    def test_frozen_immutability(self) -> None:
        r = WindowTextResult(app_name="Safari")
        with pytest.raises(AttributeError):
            r.app_name = "Chrome"  # type: ignore[misc]


class TestExtractWindowTextMacOS:
    """Tests for macos._extract_window_text (blocking function)."""

    @patch("subprocess.run")
    def test_success_full_output(self, mock_run: MagicMock) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import (
            _extract_window_text,
        )

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Chrome|||GitHub - Dashboard|||Welcome to GitHub\nSign in",
            stderr="",
        )
        result = _extract_window_text()
        assert result.success is True
        assert result.app_name == "Chrome"
        assert result.window_title == "GitHub - Dashboard"
        assert "Welcome to GitHub" in result.text
        assert result.needs_permission is False

    @patch("subprocess.run")
    def test_success_no_text(self, mock_run: MagicMock) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import (
            _extract_window_text,
        )

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Finder|||Desktop|||",
            stderr="",
        )
        result = _extract_window_text()
        assert result.success is True
        assert result.app_name == "Finder"
        assert result.window_title == "Desktop"
        assert result.text == ""

    @patch("subprocess.run")
    def test_success_only_app_name(self, mock_run: MagicMock) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import (
            _extract_window_text,
        )

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Finder",
            stderr="",
        )
        result = _extract_window_text()
        assert result.success is True
        assert result.app_name == "Finder"
        assert result.window_title == ""
        assert result.text == ""

    @patch("subprocess.run")
    def test_permission_denied_chinese(self, mock_run: MagicMock) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import (
            _extract_window_text,
        )

        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr='"osascript"不允许辅助访问。',
        )
        result = _extract_window_text()
        assert result.success is False
        assert result.needs_permission is True

    @patch("subprocess.run")
    def test_permission_denied_english(self, mock_run: MagicMock) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import (
            _extract_window_text,
        )

        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="osascript is not allowed assistive access.",
        )
        result = _extract_window_text()
        assert result.success is False
        assert result.needs_permission is True

    @patch("subprocess.run")
    def test_generic_failure(self, mock_run: MagicMock) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import (
            _extract_window_text,
        )

        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Some other error",
        )
        result = _extract_window_text()
        assert result.success is False
        assert result.needs_permission is False

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=10))
    def test_timeout(self, _mock: MagicMock) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import (
            _extract_window_text,
        )

        result = _extract_window_text()
        assert result.success is False

    @patch("subprocess.run", side_effect=OSError("No such file"))
    def test_os_error(self, _mock: MagicMock) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import (
            _extract_window_text,
        )

        result = _extract_window_text()
        assert result.success is False

    @patch("subprocess.run")
    def test_text_with_pipes(self, mock_run: MagicMock) -> None:
        """Ensure text containing ||| is handled correctly (splitn(3))."""
        from myrm_agent_harness.toolkits.computer_use.backends.macos import (
            _extract_window_text,
        )

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="VSCode|||main.py|||a = b ||| c = d",
            stderr="",
        )
        result = _extract_window_text()
        assert result.app_name == "VSCode"
        assert result.window_title == "main.py"
        assert "a = b ||| c = d" in result.text


class TestLinuxBackendWindowText:
    """Tests for LinuxBackend.window_text()."""

    @pytest.fixture
    def backend(self) -> object:
        from myrm_agent_harness.toolkits.computer_use.backends.linux import LinuxBackend
        return LinuxBackend(display_num=1)

    @pytest.mark.asyncio
    async def test_success(self, backend: object) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.linux import LinuxBackend
        assert isinstance(backend, LinuxBackend)

        with patch.object(backend, "_run_cmd", side_effect=[
            ("Terminal - bash", "", 0),
            ("12345678", "", 0),
            ('WM_CLASS(STRING) = "gnome-terminal", "Gnome-terminal"', "", 0),
        ]):
            result = await backend.window_text()

        assert result.success is True
        assert result.window_title == "Terminal - bash"
        assert result.text == ""

    @pytest.mark.asyncio
    async def test_failure(self, backend: object) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.linux import LinuxBackend
        assert isinstance(backend, LinuxBackend)

        with patch.object(
            backend,
            "_run_cmd",
            side_effect=OSError("xdotool not found"),
        ):
            result = await backend.window_text()
        assert result.success is False


class TestProtocolCompliance:
    """Both backends satisfy ComputerBackend.window_text() contract."""

    def test_macos_has_window_text(self) -> None:
        import inspect

        from myrm_agent_harness.toolkits.computer_use.backends.macos import MacOSBackend

        assert hasattr(MacOSBackend, "window_text")
        assert inspect.iscoroutinefunction(MacOSBackend.window_text)

    def test_linux_has_window_text(self) -> None:
        import inspect

        from myrm_agent_harness.toolkits.computer_use.backends.linux import LinuxBackend

        assert hasattr(LinuxBackend, "window_text")
        assert inspect.iscoroutinefunction(LinuxBackend.window_text)

    def test_protocol_defines_window_text(self) -> None:
        import inspect

        from myrm_agent_harness.toolkits.computer_use.backends.protocols import ComputerBackend

        assert hasattr(ComputerBackend, "window_text")
        sig = inspect.signature(ComputerBackend.window_text)
        assert sig.return_annotation == "WindowTextResult"
