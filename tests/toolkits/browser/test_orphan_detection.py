"""Tests for precise orphan process detection and cleanup."""

from __future__ import annotations

import importlib.util
import signal
import sys
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.doctor import (
    _extract_user_data_dir,
    _is_automation_cache_path,
    _is_automation_driver_cmdline,
    cleanup_orphan_processes,
    find_orphan_automation_processes,
    find_orphan_chromium_processes,
    find_orphan_driver_processes,
)

_PSUTIL_INSTALLED = importlib.util.find_spec("psutil") is not None

psutil_required = pytest.mark.skipif(not _PSUTIL_INSTALLED, reason="psutil not installed")


def test_extract_user_data_dir_with_equals():
    """Should extract user-data-dir with = syntax."""
    cmdline = "/usr/bin/chrome --user-data-dir=/tmp/playwright_chromium --headless"
    result = _extract_user_data_dir(cmdline)
    assert result == "/tmp/playwright_chromium"


def test_extract_user_data_dir_without_equals():
    """Should extract user-data-dir with space syntax."""
    cmdline = "/usr/bin/chrome --user-data-dir /tmp/playwright_chromium --headless"
    result = _extract_user_data_dir(cmdline)
    assert result == "/tmp/playwright_chromium"


def test_extract_user_data_dir_missing():
    """Should return empty string when user-data-dir not present."""
    cmdline = "/usr/bin/chrome --headless --no-sandbox"
    result = _extract_user_data_dir(cmdline)
    assert result == ""


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/home/user/.cache/patchright/chromium-123", True),
        ("/home/user/.cache/ms-playwright/chromium-456", True),
        ("/home/user/.cache/puppeteer/chrome/mac_arm-147", True),
        ("/var/folders/tmp/playwright_chromiumdev_profile-abc", True),
        ("/home/user/.config/google-chrome", False),
        ("/tmp/selenium_chrome", False),
        ("/Applications/Google Chrome.app", False),
    ],
)
def test_is_automation_cache_path(path: str, expected: bool):
    """Should correctly identify automation framework cache paths."""
    assert _is_automation_cache_path(path) is expected


@pytest.mark.parametrize(
    ("cmdline", "expected"),
    [
        ("/path/patchright/driver/node cli.js run-driver", True),
        ("/path/playwright/driver/node cli.js run-driver", True),
        ("/usr/bin/node server.js", False),
    ],
)
def test_is_automation_driver_cmdline(cmdline: str, expected: bool):
    assert _is_automation_driver_cmdline(cmdline) is expected


def test_find_orphan_chromium_processes_psutil_missing():
    """Should return empty list when psutil unavailable."""
    with patch.dict(sys.modules, {"psutil": None}):
        result = find_orphan_chromium_processes()
        assert result == []


@psutil_required
def test_find_orphan_chromium_processes_identifies_orphan():
    """Should identify orphan process with patchright cache path."""
    mock_proc = MagicMock()
    mock_proc.info = {
        "pid": 12345,
        "name": "chrome-headless-shell",
        "ppid": 1,
        "cmdline": [
            "/path/chrome",
            "--user-data-dir=/Users/test/.cache/ms-playwright/chromium-1208",
            "--headless",
        ],
    }

    mock_parent = MagicMock()
    mock_parent.name.return_value = "init"
    mock_parent.pid = 1
    mock_parent.parent.return_value = None

    with (
        patch("psutil.process_iter", return_value=[mock_proc]),
        patch.object(mock_proc, "parent", return_value=mock_parent),
    ):
        orphans = find_orphan_chromium_processes()
        assert len(orphans) == 1
        assert orphans[0]["pid"] == 12345
        assert "ms-playwright" in orphans[0]["user_data_dir"]


@psutil_required
def test_find_orphan_driver_processes_identifies_orphan():
    mock_proc = MagicMock()
    mock_proc.info = {
        "pid": 22222,
        "name": "node",
        "ppid": 1,
        "cmdline": [
            "/venv/lib/patchright/driver/node",
            "/venv/lib/patchright/driver/package/cli.js",
            "run-driver",
        ],
    }

    mock_parent = MagicMock()
    mock_parent.name.return_value = "init"
    mock_parent.pid = 1
    mock_parent.parent.return_value = None

    with (
        patch("psutil.process_iter", return_value=[mock_proc]),
        patch.object(mock_proc, "parent", return_value=mock_parent),
    ):
        orphans = find_orphan_driver_processes()
        assert len(orphans) == 1
        assert orphans[0]["pid"] == 22222


@psutil_required
def test_find_orphan_automation_processes_merges_chromium_and_driver():
    chromium_proc = MagicMock()
    chromium_proc.info = {
        "pid": 11111,
        "name": "chrome-headless-shell",
        "ppid": 1,
        "cmdline": [
            "/path/chrome",
            "--user-data-dir=/tmp/.cache/ms-playwright/chromium-1208",
        ],
    }
    driver_proc = MagicMock()
    driver_proc.info = {
        "pid": 22222,
        "name": "node",
        "ppid": 1,
        "cmdline": ["/venv/patchright/driver/node", "run-driver"],
    }

    mock_parent = MagicMock()
    mock_parent.name.return_value = "init"
    mock_parent.pid = 1
    mock_parent.parent.return_value = None

    with (
        patch("psutil.process_iter", return_value=[chromium_proc, driver_proc]),
        patch.object(chromium_proc, "parent", return_value=mock_parent),
        patch.object(driver_proc, "parent", return_value=mock_parent),
    ):
        orphans = find_orphan_automation_processes()
        assert {int(o["pid"]) for o in orphans} == {11111, 22222}


@psutil_required
def test_find_orphan_chromium_processes_skips_user_chrome():
    """Should skip user-launched Chrome (non-automation path)."""
    mock_proc = MagicMock()
    mock_proc.info = {
        "pid": 12345,
        "name": "Google Chrome",
        "ppid": 1,
        "cmdline": [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "--user-data-dir=/Users/test/Library/Application Support/Google/Chrome",
        ],
    }

    with patch("psutil.process_iter", return_value=[mock_proc]):
        orphans = find_orphan_chromium_processes()
        assert len(orphans) == 0


@psutil_required
def test_cleanup_orphan_processes_dry_run_default():
    """Should not kill processes when force=False (dry-run)."""
    result = cleanup_orphan_processes([12345, 67890], force=False)

    assert result["dry_run"] is True
    assert result["killed"] == 0
    assert result["would_kill"] == 2
    assert "Dry-run" in result["message"]


@psutil_required
def test_cleanup_orphan_processes_with_force():
    """Should kill processes when force=True."""
    with patch("os.kill") as mock_kill:
        result = cleanup_orphan_processes([12345], force=True)

        assert result["dry_run"] is False
        assert result["killed"] == 1
        mock_kill.assert_called_once()


@psutil_required
def test_cleanup_orphan_processes_handles_process_not_found():
    """Should handle ProcessLookupError gracefully."""
    with patch("os.kill", side_effect=ProcessLookupError):
        result = cleanup_orphan_processes([12345], force=True)

        assert result["killed"] == 0
        assert result["dry_run"] is False


@psutil_required
def test_cleanup_orphan_processes_handles_permission_error():
    """Should record permission failures."""
    with patch("os.kill", side_effect=PermissionError):
        result = cleanup_orphan_processes([12345], force=True)

        assert result["killed"] == 0
        assert len(result["failed"]) == 1
        assert result["failed"][0]["reason"] == "permission_denied"


def test_cleanup_orphan_processes_psutil_missing():
    """Should return error when psutil unavailable."""
    with patch.dict(sys.modules, {"psutil": None}):
        result = cleanup_orphan_processes([12345], force=True)

        assert result["dry_run"] is True
        assert result["killed"] == 0
        assert result["error"] == "psutil not available"


@psutil_required
def test_cleanup_orphan_processes_auto_detect():
    """Should auto-detect orphans when orphan_pids=None."""
    mock_proc = MagicMock()
    mock_proc.info = {
        "pid": 99999,
        "name": "chrome",
        "ppid": 1,
        "cmdline": [
            "/path/chrome",
            "--user-data-dir=/tmp/.cache/patchright/chromium-1234",
            "--headless",
        ],
    }

    mock_parent = MagicMock()
    mock_parent.name.return_value = "init"
    mock_parent.pid = 1
    mock_parent.parent.return_value = None

    with (
        patch("psutil.process_iter", return_value=[mock_proc]),
        patch.object(mock_proc, "parent", return_value=mock_parent),
        patch("os.kill") as mock_kill,
    ):
        result = cleanup_orphan_processes(orphan_pids=None, force=True)

        assert result["dry_run"] is False
        assert result["killed"] == 1
        mock_kill.assert_called_once_with(99999, signal.SIGTERM)


@psutil_required
def test_find_orphan_chromium_processes_scan_exception():
    """Should handle exception during process iteration."""
    with patch("psutil.process_iter", side_effect=RuntimeError("scan failed")):
        orphans = find_orphan_chromium_processes()

        assert orphans == []
