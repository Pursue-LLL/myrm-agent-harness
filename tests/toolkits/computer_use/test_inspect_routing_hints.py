"""Tests for native API routing hints in inspect_foreground().

Covers:
- macOS _SCRIPTABLE_APPS frozenset membership and _native_api_hint logic
- Windows _COM_AUTOMATABLE_APPS substring matching and _native_api_hint logic
- Linux _DBUS_AUTOMATABLE_APPS substring matching and _native_api_hint logic
- inspect_foreground() integration: routing hint appended to recommendation
- Edge cases: unknown apps return empty hint, case sensitivity
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestMacOSNativeApiHint:
    """Tests for macOS _native_api_hint and _SCRIPTABLE_APPS."""

    def test_known_app_returns_hint(self):
        from myrm_agent_harness.toolkits.computer_use.perception.macos_ax import _native_api_hint

        result = _native_api_hint("Finder")
        assert "AppleScript" in result
        assert "bash_tool" in result
        assert "osascript" in result

    def test_unknown_app_returns_empty(self):
        from myrm_agent_harness.toolkits.computer_use.perception.macos_ax import _native_api_hint

        result = _native_api_hint("SomeRandomApp")
        assert result == ""

    def test_office_apps_in_list(self):
        from myrm_agent_harness.toolkits.computer_use.perception.macos_ax import _SCRIPTABLE_APPS

        for app in ["Microsoft Excel", "Microsoft Word", "Microsoft PowerPoint", "Microsoft Outlook"]:
            assert app in _SCRIPTABLE_APPS

    def test_core_macos_apps_in_list(self):
        from myrm_agent_harness.toolkits.computer_use.perception.macos_ax import _SCRIPTABLE_APPS

        for app in ["Finder", "Mail", "Safari", "Calendar", "Notes", "Terminal"]:
            assert app in _SCRIPTABLE_APPS

    def test_adobe_apps_in_list(self):
        from myrm_agent_harness.toolkits.computer_use.perception.macos_ax import _SCRIPTABLE_APPS

        for app in ["Adobe Photoshop", "Adobe Illustrator", "Adobe Acrobat", "Adobe InDesign"]:
            assert app in _SCRIPTABLE_APPS

    def test_creative_dev_apps_in_list(self):
        from myrm_agent_harness.toolkits.computer_use.perception.macos_ax import _SCRIPTABLE_APPS

        for app in ["Sketch", "Final Cut Pro", "WPS Office", "Firefox", "Visual Studio Code", "Cursor"]:
            assert app in _SCRIPTABLE_APPS

    def test_case_sensitive_matching(self):
        from myrm_agent_harness.toolkits.computer_use.perception.macos_ax import _native_api_hint

        assert _native_api_hint("finder") == ""
        assert _native_api_hint("FINDER") == ""
        assert "AppleScript" in _native_api_hint("Finder")

    def test_hint_includes_app_name(self):
        from myrm_agent_harness.toolkits.computer_use.perception.macos_ax import _native_api_hint

        result = _native_api_hint("Mail")
        assert "'Mail'" in result

    @patch("myrm_agent_harness.toolkits.computer_use.perception.macos_ax.capture_ax_snapshot")
    def test_inspect_foreground_appends_hint(self, mock_snapshot):
        from myrm_agent_harness.toolkits.computer_use.perception.macos_ax import (
            MacAxSnapshot,
            inspect_foreground,
        )
        from myrm_agent_harness.toolkits.element_ref.types import SnapshotMeta

        meta = SnapshotMeta(ref_count=5, app_name="Finder", window_title="Desktop", scope="foreground")
        mock_snapshot.return_value = MacAxSnapshot(meta=meta, refs={})

        result = inspect_foreground()
        assert result["app_name"] == "Finder"
        rec = result["recommendation"]
        assert "desktop_snapshot_tool" in rec
        assert "AppleScript" in rec
        assert "bash_tool" in rec

    @patch("myrm_agent_harness.toolkits.computer_use.perception.macos_ax.capture_ax_snapshot")
    def test_inspect_foreground_no_hint_for_unknown(self, mock_snapshot):
        from myrm_agent_harness.toolkits.computer_use.perception.macos_ax import (
            MacAxSnapshot,
            inspect_foreground,
        )
        from myrm_agent_harness.toolkits.element_ref.types import SnapshotMeta

        meta = SnapshotMeta(ref_count=3, app_name="UnknownApp", window_title="", scope="foreground")
        mock_snapshot.return_value = MacAxSnapshot(meta=meta, refs={})

        result = inspect_foreground()
        rec = result["recommendation"]
        assert "desktop_snapshot_tool" in rec
        assert "AppleScript" not in rec


class TestWindowsNativeApiHint:
    """Tests for Windows _native_api_hint and _COM_AUTOMATABLE_APPS."""

    def test_exact_match(self):
        from myrm_agent_harness.toolkits.computer_use.perception.windows_ax import _native_api_hint

        result = _native_api_hint("Microsoft Excel")
        assert "COM/PowerShell" in result
        assert "bash_tool" in result

    def test_window_title_substring_match(self):
        from myrm_agent_harness.toolkits.computer_use.perception.windows_ax import _native_api_hint

        result = _native_api_hint("Book1.xlsx - Microsoft Excel")
        assert "COM/PowerShell" in result

    def test_unknown_app_returns_empty(self):
        from myrm_agent_harness.toolkits.computer_use.perception.windows_ax import _native_api_hint

        result = _native_api_hint("Random App - Something Else")
        assert result == ""

    def test_case_insensitive_matching(self):
        from myrm_agent_harness.toolkits.computer_use.perception.windows_ax import _native_api_hint

        result = _native_api_hint("MICROSOFT EXCEL")
        assert "COM/PowerShell" in result

    def test_office_suite_coverage(self):
        from myrm_agent_harness.toolkits.computer_use.perception.windows_ax import _COM_AUTOMATABLE_APPS

        for app in ["Microsoft Excel", "Microsoft Word", "Microsoft PowerPoint", "Microsoft Outlook"]:
            assert app in _COM_AUTOMATABLE_APPS

    def test_adobe_and_wps_in_windows_list(self):
        from myrm_agent_harness.toolkits.computer_use.perception.windows_ax import _COM_AUTOMATABLE_APPS

        for app in ["Adobe Photoshop", "Adobe Illustrator", "WPS", "WPS Office", "AutoCAD"]:
            assert app in _COM_AUTOMATABLE_APPS

    def test_dev_tools_in_windows_list(self):
        from myrm_agent_harness.toolkits.computer_use.perception.windows_ax import _COM_AUTOMATABLE_APPS

        for app in ["Visual Studio Code", "Cursor", "Firefox"]:
            assert app in _COM_AUTOMATABLE_APPS


class TestLinuxNativeApiHint:
    """Tests for Linux _native_api_hint and _DBUS_AUTOMATABLE_APPS."""

    def test_known_app_returns_hint(self):
        from myrm_agent_harness.toolkits.computer_use.perception.linux_ax import _native_api_hint

        result = _native_api_hint("nautilus")
        assert "D-Bus" in result
        assert "bash_tool" in result

    def test_case_insensitive_matching(self):
        from myrm_agent_harness.toolkits.computer_use.perception.linux_ax import _native_api_hint

        result = _native_api_hint("Nautilus")
        assert "D-Bus" in result

    def test_unknown_app_returns_empty(self):
        from myrm_agent_harness.toolkits.computer_use.perception.linux_ax import _native_api_hint

        result = _native_api_hint("random-app")
        assert result == ""

    def test_libreoffice_detected(self):
        from myrm_agent_harness.toolkits.computer_use.perception.linux_ax import _native_api_hint

        result = _native_api_hint("LibreOffice Writer")
        assert "D-Bus" in result

    def test_gnome_apps_coverage(self):
        from myrm_agent_harness.toolkits.computer_use.perception.linux_ax import _DBUS_AUTOMATABLE_APPS

        for app in ["nautilus", "Files", "Thunderbird", "LibreOffice", "GNOME Terminal"]:
            assert app in _DBUS_AUTOMATABLE_APPS

    def test_new_linux_apps_in_list(self):
        from myrm_agent_harness.toolkits.computer_use.perception.linux_ax import _DBUS_AUTOMATABLE_APPS

        for app in ["Firefox", "GIMP", "Inkscape", "VLC", "WPS Office", "Okular"]:
            assert app in _DBUS_AUTOMATABLE_APPS

    def test_firefox_detected_via_subprocess_name(self):
        from myrm_agent_harness.toolkits.computer_use.perception.linux_ax import _native_api_hint

        result = _native_api_hint("Firefox Web Browser")
        assert "D-Bus" in result
