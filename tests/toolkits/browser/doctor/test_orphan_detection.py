"""Tests for precise orphan process detection (process-table scan and ancestry rules)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, create_autospec, patch

import psutil

from myrm_agent_harness.toolkits.browser.doctor import (
    find_orphan_automation_processes,
    find_orphan_chromium_processes,
    find_orphan_driver_processes,
)


def test_find_orphan_chromium_processes_psutil_missing() -> None:
    """Should return empty list when psutil unavailable."""
    with patch.dict(sys.modules, {"psutil": None}):
        result = find_orphan_chromium_processes()
        assert result == []


def test_find_orphan_chromium_processes_identifies_orphan() -> None:
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


def test_find_orphan_driver_processes_identifies_orphan() -> None:
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


def test_find_orphan_automation_processes_merges_chromium_and_driver() -> None:
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


def test_find_orphan_chromium_processes_skips_user_chrome() -> None:
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


def test_find_orphan_chromium_processes_scan_exception() -> None:
    """Should handle exception during process iteration."""
    with patch("psutil.process_iter", side_effect=RuntimeError("scan failed")):
        orphans = find_orphan_chromium_processes()

        assert orphans == []


def test_find_orphan_chromium_skips_empty_cmdline() -> None:
    """Should skip chromium processes with an empty cmdline."""
    mock_proc = MagicMock()
    mock_proc.info = {
        "pid": 12345,
        "name": "chrome-headless-shell",
        "ppid": 1,
        "cmdline": [],
    }

    with patch("psutil.process_iter", return_value=[mock_proc]):
        orphans = find_orphan_chromium_processes()

        assert orphans == []


def test_find_orphan_chromium_skips_missing_user_data_dir() -> None:
    """Should skip chromium without a user-data-dir flag."""
    mock_proc = MagicMock()
    mock_proc.info = {
        "pid": 12345,
        "name": "chrome-headless-shell",
        "ppid": 1,
        "cmdline": ["/path/chrome", "--headless", "--no-sandbox"],
    }

    with patch("psutil.process_iter", return_value=[mock_proc]):
        orphans = find_orphan_chromium_processes()

        assert orphans == []


def test_find_orphan_chromium_skips_empty_user_data_dir_value() -> None:
    """Should skip chromium whose user-data-dir flag has no value."""
    mock_proc = MagicMock()
    mock_proc.info = {
        "pid": 12345,
        "name": "chrome",
        "ppid": 1,
        "cmdline": ["/path/chrome", "--user-data-dir="],
    }

    with patch("psutil.process_iter", return_value=[mock_proc]):
        orphans = find_orphan_chromium_processes()

        assert orphans == []


def test_find_orphan_chromium_skips_process_with_python_ancestor() -> None:
    """Should skip automation processes that still have a python parent."""
    mock_proc = create_autospec(psutil.Process)
    mock_proc.info = {
        "pid": 12345,
        "name": "chrome",
        "ppid": 9999,
        "cmdline": [
            "/path/chrome",
            "--user-data-dir=/tmp/.cache/patchright/chromium-123",
        ],
    }
    parent = create_autospec(psutil.Process)
    parent.pid = 9999
    parent.name.return_value = "python3.13"
    parent.parent.return_value = None
    mock_proc.parent.return_value = parent

    with patch("psutil.process_iter", return_value=[mock_proc]):
        orphans = find_orphan_chromium_processes()

        assert orphans == []


def test_find_orphan_chromium_skips_non_automation_cache() -> None:
    """Should skip chromium using a non-automation profile path."""
    mock_proc = MagicMock()
    mock_proc.info = {
        "pid": 12345,
        "name": "chrome",
        "ppid": 1,
        "cmdline": ["/path/chrome", "--user-data-dir=/tmp/selenium_chrome"],
    }

    with patch("psutil.process_iter", return_value=[mock_proc]):
        orphans = find_orphan_chromium_processes()

        assert orphans == []


def test_find_orphan_chromium_handles_access_denied() -> None:
    """Should tolerate AccessDenied raised while scanning a process."""
    mock_proc = MagicMock()
    mock_proc.info = {
        "pid": 12345,
        "name": "chrome",
        "ppid": 1,
        "cmdline": [
            "/path/chrome",
            "--user-data-dir=/tmp/.cache/patchright/chromium-123",
        ],
    }

    with (
        patch("psutil.process_iter", return_value=[mock_proc]),
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.orphans._has_python_ancestor",
            side_effect=psutil.AccessDenied(),
        ),
    ):
        orphans = find_orphan_chromium_processes()

        assert orphans == []


def test_find_orphan_driver_psutil_missing() -> None:
    """Should return empty list when psutil unavailable."""
    with patch.dict(sys.modules, {"psutil": None}):
        orphans = find_orphan_driver_processes()

        assert orphans == []


def test_find_orphan_driver_skips_empty_cmdline() -> None:
    """Should skip driver processes with an empty cmdline."""
    mock_proc = MagicMock()
    mock_proc.info = {
        "pid": 22222,
        "name": "node",
        "ppid": 1,
        "cmdline": [],
    }

    with patch("psutil.process_iter", return_value=[mock_proc]):
        orphans = find_orphan_driver_processes()

        assert orphans == []


def test_find_orphan_driver_handles_access_denied() -> None:
    """Should tolerate AccessDenied while scanning a driver process."""
    mock_proc = MagicMock()
    mock_proc.info = {
        "pid": 22222,
        "name": "node",
        "ppid": 1,
        "cmdline": ["/venv/patchright/driver/node", "run-driver"],
    }

    with (
        patch("psutil.process_iter", return_value=[mock_proc]),
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.orphans._has_python_ancestor",
            side_effect=psutil.AccessDenied(),
        ),
    ):
        orphans = find_orphan_driver_processes()

        assert orphans == []


def test_find_orphan_automation_deduplicates_pids() -> None:
    """Should merge both scans and drop duplicate pids."""
    dup = {
        "pid": 12345,
        "name": "chrome",
        "ppid": 1,
        "user_data_dir": "/tmp/x",
    }

    with (
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.orphans.find_orphan_chromium_processes",
            return_value=[dup],
        ),
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.orphans.find_orphan_driver_processes",
            return_value=[dup],
        ),
    ):
        orphans = find_orphan_automation_processes()

        assert len(orphans) == 1
        assert orphans[0]["pid"] == 12345


def test_find_orphan_driver_scan_exception() -> None:
    """Should handle exception during driver process iteration."""
    with patch("psutil.process_iter", side_effect=RuntimeError("scan failed")):
        orphans = find_orphan_driver_processes()

        assert orphans == []
