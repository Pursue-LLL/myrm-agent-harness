"""Tests for precise orphan process detection and cleanup."""

from __future__ import annotations

import importlib.util
import os
import signal
import sys
from unittest.mock import MagicMock, create_autospec, patch

import pytest

from myrm_agent_harness.toolkits.browser.doctor import (
    CheckStatus,
    _extract_user_data_dir,
    _is_automation_cache_path,
    _is_automation_driver_cmdline,
    cleanup_orphan_processes,
    find_orphan_automation_processes,
    find_orphan_chromium_processes,
    find_orphan_driver_processes,
)
from myrm_agent_harness.toolkits.browser.doctor.orphans import (
    _has_python_ancestor,
    check_orphan_processes,
)

_PSUTIL_INSTALLED = importlib.util.find_spec("psutil") is not None
if _PSUTIL_INSTALLED:
    import psutil

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


@psutil_required
def test_find_orphan_chromium_skips_empty_cmdline():
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


@psutil_required
def test_find_orphan_chromium_skips_missing_user_data_dir():
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


@psutil_required
def test_find_orphan_chromium_skips_empty_user_data_dir_value():
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


@psutil_required
def test_find_orphan_chromium_skips_process_with_python_ancestor():
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


@psutil_required
def test_find_orphan_chromium_skips_non_automation_cache():
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


@psutil_required
def test_find_orphan_chromium_handles_access_denied():
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


def test_find_orphan_driver_psutil_missing():
    """Should return empty list when psutil unavailable."""
    with patch.dict(sys.modules, {"psutil": None}):
        orphans = find_orphan_driver_processes()

        assert orphans == []


@psutil_required
def test_find_orphan_driver_skips_empty_cmdline():
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


@psutil_required
def test_find_orphan_driver_handles_access_denied():
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


@psutil_required
def test_find_orphan_automation_deduplicates_pids():
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


@psutil_required
def test_has_python_ancestor_matches_current_tree():
    """Should flag a process whose parent is inside the current process tree."""
    proc = create_autospec(psutil.Process)
    parent = create_autospec(psutil.Process)
    parent.pid = os.getpid()
    parent.name.return_value = "node"
    parent.parent.return_value = None
    proc.parent.return_value = parent

    assert _has_python_ancestor(proc, os.getpid()) is True


@psutil_required
def test_has_python_ancestor_matches_python_parent():
    """Should flag a process whose parent chain contains a python process."""
    proc = create_autospec(psutil.Process)
    parent = create_autospec(psutil.Process)
    parent.pid = 9999
    parent.name.return_value = "python3.13"
    parent.parent.return_value = None
    proc.parent.return_value = parent

    assert _has_python_ancestor(proc, os.getpid()) is True


@psutil_required
def test_has_python_ancestor_returns_false_when_chain_ends():
    """Should return False when the parent chain has no python or tree match."""
    proc = create_autospec(psutil.Process)
    leaf = create_autospec(psutil.Process)
    leaf.pid = 9998
    leaf.name.return_value = "node"
    leaf.parent.return_value = None
    proc.parent.return_value = leaf

    assert _has_python_ancestor(proc, os.getpid()) is False


@psutil_required
def test_has_python_ancestor_tolerates_unexpected_error():
    """Should conservatively flag the process when the walk raises unexpectedly."""
    proc = create_autospec(psutil.Process)
    proc.parent.side_effect = RuntimeError("boom")

    assert _has_python_ancestor(proc, os.getpid()) is True


@psutil_required
def test_has_python_ancestor_breaks_when_parent_name_denied():
    """Should stop walking when a parent's name cannot be read."""
    proc = create_autospec(psutil.Process)
    parent = create_autospec(psutil.Process)
    parent.pid = 9997
    parent.name.side_effect = psutil.AccessDenied()
    parent.parent.return_value = None
    proc.parent.return_value = parent

    assert _has_python_ancestor(proc, os.getpid()) is False


@psutil_required
def test_has_python_ancestor_breaks_when_parent_walk_denied():
    """Should stop walking when reaching a parent raises AccessDenied."""
    proc = create_autospec(psutil.Process)
    parent = create_autospec(psutil.Process)
    parent.pid = 9996
    parent.name.return_value = "node"
    parent.parent.side_effect = psutil.AccessDenied()
    proc.parent.return_value = parent

    assert _has_python_ancestor(proc, os.getpid()) is False


@psutil_required
def test_has_python_ancestor_returns_false_when_current_proc_gone():
    """Should return False when the current process itself is gone."""
    proc = create_autospec(psutil.Process)

    with patch("psutil.Process", side_effect=psutil.NoSuchProcess(999)):
        assert _has_python_ancestor(proc, os.getpid()) is False


@psutil_required
def test_find_orphan_driver_scan_exception():
    """Should handle exception during driver process iteration."""
    with patch("psutil.process_iter", side_effect=RuntimeError("scan failed")):
        orphans = find_orphan_driver_processes()

        assert orphans == []


@psutil_required
def test_cleanup_orphan_processes_handles_generic_exception():
    """Should record any unexpected kill failure with its reason."""
    with patch("os.kill", side_effect=RuntimeError("signal failed")):
        result = cleanup_orphan_processes([12345], force=True)

        assert result["killed"] == 0
        assert result["failed"] == [{"pid": 12345, "reason": "signal failed"}]


@psutil_required
def test_check_orphan_processes_previews_only_first_pids():
    """Should preview only the first three pids when many orphans exist."""
    orphans = [
        {"pid": pid, "name": "chrome", "ppid": 1, "user_data_dir": "/tmp/x"}
        for pid in (1111, 2222, 3333, 4444)
    ]

    with patch(
        "myrm_agent_harness.toolkits.browser.doctor.orphans.find_orphan_automation_processes",
        return_value=orphans,
    ):
        result = check_orphan_processes()

    assert result.status == CheckStatus.WARNING
    assert "4 orphan automation" in result.message
    assert "..." in result.message
    assert result.details == {
        "count": 4,
        "pids": [1111, 2222, 3333, 4444],
        "paths": ["/tmp/x", "/tmp/x", "/tmp/x", "/tmp/x"],
    }
