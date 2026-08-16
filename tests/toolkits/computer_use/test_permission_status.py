"""Tests for OS permission probing — PermissionStatus dataclass and macOS check logic.

Covers:
- PermissionStatus frozen dataclass: defaults, all_granted property, deeplinks
- _check_accessibility: AXIsProcessTrusted + osascript capability probe
- _osascript_ax_capable: osascript subprocess probe scenarios
- _check_screen_recording: CGPreflightScreenCaptureAccess via ctypes mocking
- _check_macos_permissions: integration of both checks into PermissionStatus
- MacOSBackend.check_permissions: async wrapper delegates to blocking impl
"""

from __future__ import annotations

import subprocess
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.types import PermissionStatus


class TestPermissionStatus:
    """PermissionStatus dataclass invariants."""

    def test_defaults_all_granted(self) -> None:
        status = PermissionStatus()
        assert status.accessibility is True
        assert status.screen_recording is True
        assert status.all_granted is True
        assert status.platform == ""
        assert status.settings_deeplinks == {}

    def test_all_granted_both_true(self) -> None:
        status = PermissionStatus(accessibility=True, screen_recording=True)
        assert status.all_granted is True

    def test_all_granted_accessibility_false(self) -> None:
        status = PermissionStatus(accessibility=False, screen_recording=True)
        assert status.all_granted is False

    def test_all_granted_screen_recording_false(self) -> None:
        status = PermissionStatus(accessibility=True, screen_recording=False)
        assert status.all_granted is False

    def test_all_granted_both_false(self) -> None:
        status = PermissionStatus(accessibility=False, screen_recording=False)
        assert status.all_granted is False

    def test_frozen_cannot_mutate(self) -> None:
        status = PermissionStatus()
        with pytest.raises(FrozenInstanceError):
            status.accessibility = False  # type: ignore[misc]

    def test_platform_and_deeplinks(self) -> None:
        deeplinks = {"accessibility": "url://a", "screen_recording": "url://b"}
        status = PermissionStatus(
            accessibility=True,
            screen_recording=False,
            platform="macos",
            settings_deeplinks=deeplinks,
        )
        assert status.platform == "macos"
        assert status.settings_deeplinks == deeplinks
        assert status.all_granted is False


class TestCheckAccessibility:
    """_check_accessibility via ctypes AXIsProcessTrusted + osascript probe mocking."""

    def test_granted_when_process_and_osascript_trusted(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import _check_accessibility

        mock_ax = MagicMock()
        mock_ax.AXIsProcessTrusted.return_value = True
        mock_ax.AXIsProcessTrusted.restype = None

        with (
            patch("ctypes.util.find_library", return_value="/System/Library/ApplicationServices"),
            patch("ctypes.cdll.LoadLibrary", return_value=mock_ax),
            patch(
                "myrm_agent_harness.toolkits.computer_use.backends.macos._osascript_ax_capable",
                return_value=True,
            ),
        ):
            assert _check_accessibility() is True
            mock_ax.AXIsProcessTrusted.assert_called_once_with()

    def test_denied_when_process_not_trusted(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import _check_accessibility

        mock_ax = MagicMock()
        mock_ax.AXIsProcessTrusted.return_value = False
        mock_ax.AXIsProcessTrusted.restype = None

        with (
            patch("ctypes.util.find_library", return_value="/System/Library/ApplicationServices"),
            patch("ctypes.cdll.LoadLibrary", return_value=mock_ax),
        ):
            assert _check_accessibility() is False

    def test_denied_when_osascript_not_trusted(self) -> None:
        """Partial grant (Python trusted, osascript denied) must report false."""
        from myrm_agent_harness.toolkits.computer_use.backends.macos import _check_accessibility

        mock_ax = MagicMock()
        mock_ax.AXIsProcessTrusted.return_value = True
        mock_ax.AXIsProcessTrusted.restype = None

        with (
            patch("ctypes.util.find_library", return_value="/System/Library/ApplicationServices"),
            patch("ctypes.cdll.LoadLibrary", return_value=mock_ax),
            patch(
                "myrm_agent_harness.toolkits.computer_use.backends.macos._osascript_ax_capable",
                return_value=False,
            ),
        ):
            assert _check_accessibility() is False

    def test_denied_when_library_not_found(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import _check_accessibility

        with patch("ctypes.util.find_library", return_value=None):
            assert _check_accessibility() is False

    def test_denied_on_load_failure(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import _check_accessibility

        with (
            patch("ctypes.util.find_library", return_value="/System/Library/ApplicationServices"),
            patch("ctypes.cdll.LoadLibrary", side_effect=OSError("load failed")),
        ):
            assert _check_accessibility() is False


class TestCheckScreenRecording:
    """_check_screen_recording via ctypes mocking."""

    def test_granted_when_preflight_returns_true(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import _check_screen_recording

        mock_cg = MagicMock()
        mock_cg.CGPreflightScreenCaptureAccess.return_value = True
        mock_cg.CGPreflightScreenCaptureAccess.restype = None

        with (
            patch("ctypes.util.find_library", return_value="/System/Library/CoreGraphics"),
            patch("ctypes.cdll.LoadLibrary", return_value=mock_cg),
        ):
            assert _check_screen_recording() is True

    def test_denied_when_preflight_returns_false(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import _check_screen_recording

        mock_cg = MagicMock()
        mock_cg.CGPreflightScreenCaptureAccess.return_value = False
        mock_cg.CGPreflightScreenCaptureAccess.restype = None

        with (
            patch("ctypes.util.find_library", return_value="/System/Library/CoreGraphics"),
            patch("ctypes.cdll.LoadLibrary", return_value=mock_cg),
        ):
            assert _check_screen_recording() is False

    def test_denied_when_library_not_found(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import _check_screen_recording

        with patch("ctypes.util.find_library", return_value=None):
            assert _check_screen_recording() is False

    def test_denied_on_load_failure(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import _check_screen_recording

        with (
            patch("ctypes.util.find_library", return_value="/System/Library/CoreGraphics"),
            patch("ctypes.cdll.LoadLibrary", side_effect=OSError("load failed")),
        ):
            assert _check_screen_recording() is False


class TestOsascriptAxCapable:
    """_osascript_ax_capable probe behavior."""

    def test_capable_when_process_name_returned(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import _osascript_ax_capable

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Cursor.real\n"
        with patch(
            "myrm_agent_harness.toolkits.computer_use.backends.macos.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            assert _osascript_ax_capable() is True
            argv = mock_run.call_args.args[0]
            assert argv[0] == "osascript"
            script = argv[2]
            assert "get name of every process" in script
            assert "frontmost" in script

    def test_denied_when_nonzero_returncode(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import _osascript_ax_capable

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch(
            "myrm_agent_harness.toolkits.computer_use.backends.macos.subprocess.run",
            return_value=mock_result,
        ):
            assert _osascript_ax_capable() is False

    def test_denied_on_oserror(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import _osascript_ax_capable

        with patch(
            "myrm_agent_harness.toolkits.computer_use.backends.macos.subprocess.run",
            side_effect=OSError("osascript not found"),
        ):
            assert _osascript_ax_capable() is False

    def test_denied_on_timeout(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import _osascript_ax_capable

        with patch(
            "myrm_agent_harness.toolkits.computer_use.backends.macos.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["osascript"], timeout=5),
        ):
            assert _osascript_ax_capable() is False


class TestCheckMacosPermissions:
    """_check_macos_permissions integration."""

    def test_both_granted(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import (
            _MACOS_DEEPLINKS,
            _check_macos_permissions,
        )

        with (
            patch(
                "myrm_agent_harness.toolkits.computer_use.backends.macos._check_accessibility",
                return_value=True,
            ),
            patch(
                "myrm_agent_harness.toolkits.computer_use.backends.macos._check_screen_recording",
                return_value=True,
            ),
        ):
            status = _check_macos_permissions()
            assert status.accessibility is True
            assert status.screen_recording is True
            assert status.all_granted is True
            assert status.platform == "macos"
            assert status.settings_deeplinks == _MACOS_DEEPLINKS

    def test_accessibility_denied(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import _check_macos_permissions

        with (
            patch(
                "myrm_agent_harness.toolkits.computer_use.backends.macos._check_accessibility",
                return_value=False,
            ),
            patch(
                "myrm_agent_harness.toolkits.computer_use.backends.macos._check_screen_recording",
                return_value=True,
            ),
        ):
            status = _check_macos_permissions()
            assert status.accessibility is False
            assert status.screen_recording is True
            assert status.all_granted is False

    def test_screen_recording_denied(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import _check_macos_permissions

        with (
            patch(
                "myrm_agent_harness.toolkits.computer_use.backends.macos._check_accessibility",
                return_value=True,
            ),
            patch(
                "myrm_agent_harness.toolkits.computer_use.backends.macos._check_screen_recording",
                return_value=False,
            ),
        ):
            status = _check_macos_permissions()
            assert status.accessibility is True
            assert status.screen_recording is False
            assert status.all_granted is False

    def test_both_denied(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import _check_macos_permissions

        with (
            patch(
                "myrm_agent_harness.toolkits.computer_use.backends.macos._check_accessibility",
                return_value=False,
            ),
            patch(
                "myrm_agent_harness.toolkits.computer_use.backends.macos._check_screen_recording",
                return_value=False,
            ),
        ):
            status = _check_macos_permissions()
            assert status.accessibility is False
            assert status.screen_recording is False
            assert status.all_granted is False

    def test_deeplinks_contain_required_keys(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import _MACOS_DEEPLINKS

        assert "accessibility" in _MACOS_DEEPLINKS
        assert "screen_recording" in _MACOS_DEEPLINKS
        assert "x-apple.systempreferences:" in _MACOS_DEEPLINKS["accessibility"]
        assert "x-apple.systempreferences:" in _MACOS_DEEPLINKS["screen_recording"]


class TestMacOSBackendCheckPermissions:
    """MacOSBackend.check_permissions async wrapper."""

    @pytest.mark.asyncio
    async def test_delegates_to_blocking_impl(self) -> None:
        from myrm_agent_harness.toolkits.computer_use.backends.macos import MacOSBackend

        backend = MacOSBackend()
        expected = PermissionStatus(
            accessibility=True,
            screen_recording=False,
            platform="macos",
            settings_deeplinks={"accessibility": "url://a"},
        )
        with patch(
            "myrm_agent_harness.toolkits.computer_use.backends.macos._check_macos_permissions",
            return_value=expected,
        ):
            result = await backend.check_permissions()
            assert result is expected
            assert result.accessibility is True
            assert result.screen_recording is False
