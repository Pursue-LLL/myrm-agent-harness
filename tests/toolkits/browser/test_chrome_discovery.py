"""Unit tests for chrome_discovery module.

Tests the DevToolsActivePort-based browser discovery mechanism,
including platform-specific directory scanning, port file parsing,
HTTP/TCP probes, and the full discovery orchestration.

All network I/O is mocked — no real browsers or ports needed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.pool.chrome_discovery import (
    _read_devtools_active_port,
    discover_chrome_cdp_endpoint,
    get_chromium_data_dirs,
)


class TestGetChromiumDataDirs:
    """Test platform-specific browser data directory discovery."""

    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery.platform")
    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery._get_home")
    def test_macos_directories(self, mock_home: MagicMock, mock_platform: MagicMock, tmp_path: Path) -> None:
        mock_platform.system.return_value = "Darwin"
        mock_home.return_value = tmp_path

        base = tmp_path / "Library" / "Application Support"
        chrome_dir = base / "Google" / "Chrome"
        edge_dir = base / "Microsoft Edge"
        chrome_dir.mkdir(parents=True)
        edge_dir.mkdir(parents=True)

        dirs = list(get_chromium_data_dirs())
        assert chrome_dir in dirs
        assert edge_dir in dirs
        assert len(dirs) == 2

    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery.platform")
    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery._get_home")
    def test_linux_directories(self, mock_home: MagicMock, mock_platform: MagicMock, tmp_path: Path) -> None:
        mock_platform.system.return_value = "Linux"
        mock_home.return_value = tmp_path

        base = tmp_path / ".config"
        chrome_dir = base / "google-chrome"
        chrome_dir.mkdir(parents=True)

        dirs = list(get_chromium_data_dirs())
        assert chrome_dir in dirs
        assert len(dirs) == 1

    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery.platform")
    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery._get_home")
    def test_windows_directories(self, mock_home: MagicMock, mock_platform: MagicMock, tmp_path: Path) -> None:
        mock_platform.system.return_value = "Windows"
        mock_home.return_value = tmp_path

        with patch.dict("os.environ", {"LOCALAPPDATA": str(tmp_path)}):
            chrome_dir = tmp_path / "Google" / "Chrome" / "User Data"
            chrome_dir.mkdir(parents=True)

            dirs = list(get_chromium_data_dirs())
            assert chrome_dir in dirs

    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery.platform")
    def test_unsupported_os_yields_nothing(self, mock_platform: MagicMock) -> None:
        mock_platform.system.return_value = "FreeBSD"
        dirs = list(get_chromium_data_dirs())
        assert dirs == []

    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery.platform")
    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery._get_home")
    def test_nonexistent_dirs_filtered(self, mock_home: MagicMock, mock_platform: MagicMock, tmp_path: Path) -> None:
        mock_platform.system.return_value = "Darwin"
        mock_home.return_value = tmp_path
        dirs = list(get_chromium_data_dirs())
        assert dirs == []

    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery.platform")
    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery._get_home")
    def test_priority_order_chrome_before_edge(
        self, mock_home: MagicMock, mock_platform: MagicMock, tmp_path: Path
    ) -> None:
        mock_platform.system.return_value = "Darwin"
        mock_home.return_value = tmp_path

        base = tmp_path / "Library" / "Application Support"
        for name in ["Google/Chrome", "Microsoft Edge", "Chromium", "BraveSoftware/Brave-Browser"]:
            (base / name).mkdir(parents=True)

        dirs = list(get_chromium_data_dirs())
        names = [d.name for d in dirs]
        assert names.index("Chrome") < names.index("Microsoft Edge")


class TestReadDevToolsActivePort:
    """Test DevToolsActivePort file parsing."""

    def test_valid_two_line_file(self, tmp_path: Path) -> None:
        port_file = tmp_path / "DevToolsActivePort"
        port_file.write_text("54321\n/devtools/browser/abc-123\n")
        result = _read_devtools_active_port(tmp_path)
        assert result is not None
        port, ws_path = result
        assert port == 54321
        assert ws_path == "/devtools/browser/abc-123"

    def test_single_line_port_only(self, tmp_path: Path) -> None:
        port_file = tmp_path / "DevToolsActivePort"
        port_file.write_text("9222\n")
        result = _read_devtools_active_port(tmp_path)
        assert result is not None
        port, ws_path = result
        assert port == 9222
        assert ws_path == "/devtools/browser"

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert _read_devtools_active_port(tmp_path) is None

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        port_file = tmp_path / "DevToolsActivePort"
        port_file.write_text("")
        assert _read_devtools_active_port(tmp_path) is None

    def test_invalid_port_returns_none(self, tmp_path: Path) -> None:
        port_file = tmp_path / "DevToolsActivePort"
        port_file.write_text("not_a_number\n")
        assert _read_devtools_active_port(tmp_path) is None

    def test_port_out_of_range_returns_none(self, tmp_path: Path) -> None:
        port_file = tmp_path / "DevToolsActivePort"
        port_file.write_text("99999\n")
        assert _read_devtools_active_port(tmp_path) is None

    def test_zero_port_returns_none(self, tmp_path: Path) -> None:
        port_file = tmp_path / "DevToolsActivePort"
        port_file.write_text("0\n")
        assert _read_devtools_active_port(tmp_path) is None


class TestDiscoverChromeEndpoint:
    """Test the full discovery orchestration."""

    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery._probe_http_version")
    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery._read_devtools_active_port")
    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery.get_chromium_data_dirs")
    def test_http_probe_success(
        self, mock_dirs: MagicMock, mock_read: MagicMock, mock_probe: MagicMock
    ) -> None:
        mock_dirs.return_value = iter([Path("/fake/chrome")])
        mock_read.return_value = (54321, "/devtools/browser/abc")
        mock_probe.return_value = "ws://127.0.0.1:54321/devtools/browser/abc"

        result = discover_chrome_cdp_endpoint()
        assert result == "http://127.0.0.1:54321"
        mock_probe.assert_called_once_with(54321)

    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery._port_is_open")
    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery._probe_http_version")
    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery._read_devtools_active_port")
    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery.get_chromium_data_dirs")
    def test_tcp_fallback_on_http_failure(
        self, mock_dirs: MagicMock, mock_read: MagicMock, mock_probe: MagicMock, mock_tcp: MagicMock
    ) -> None:
        mock_dirs.return_value = iter([Path("/fake/chrome")])
        mock_read.return_value = (54321, "/devtools/browser/abc")
        mock_probe.return_value = None
        mock_tcp.return_value = True

        result = discover_chrome_cdp_endpoint()
        assert result == "http://127.0.0.1:54321"

    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery._probe_http_version")
    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery.get_chromium_data_dirs")
    def test_fallback_to_9222(self, mock_dirs: MagicMock, mock_probe: MagicMock) -> None:
        mock_dirs.return_value = iter([])
        mock_probe.return_value = "ws://127.0.0.1:9222/devtools/browser"

        result = discover_chrome_cdp_endpoint()
        assert result == "http://127.0.0.1:9222"

    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery._probe_http_version")
    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery.get_chromium_data_dirs")
    def test_returns_none_when_nothing_found(self, mock_dirs: MagicMock, mock_probe: MagicMock) -> None:
        mock_dirs.return_value = iter([])
        mock_probe.return_value = None

        result = discover_chrome_cdp_endpoint()
        assert result is None

    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery._port_is_open")
    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery._probe_http_version")
    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery._read_devtools_active_port")
    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery.get_chromium_data_dirs")
    def test_skips_stale_port_file(
        self, mock_dirs: MagicMock, mock_read: MagicMock, mock_probe: MagicMock, mock_tcp: MagicMock
    ) -> None:
        mock_dirs.return_value = iter([Path("/fake/chrome")])
        mock_read.return_value = (54321, "/devtools/browser/abc")
        mock_probe.side_effect = [None, None]
        mock_tcp.return_value = False

        result = discover_chrome_cdp_endpoint()
        assert result is None

    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery._probe_http_version")
    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery._read_devtools_active_port")
    @patch("myrm_agent_harness.toolkits.browser.pool.chrome_discovery.get_chromium_data_dirs")
    def test_tries_multiple_browsers_in_order(
        self, mock_dirs: MagicMock, mock_read: MagicMock, mock_probe: MagicMock
    ) -> None:
        chrome_dir = Path("/fake/chrome")
        edge_dir = Path("/fake/edge")
        mock_dirs.return_value = iter([chrome_dir, edge_dir])
        mock_read.side_effect = [None, (9333, "/devtools/browser/xyz")]
        mock_probe.return_value = "ws://127.0.0.1:9333/devtools/browser/xyz"

        result = discover_chrome_cdp_endpoint()
        assert result == "http://127.0.0.1:9333"
        assert mock_read.call_count == 2
