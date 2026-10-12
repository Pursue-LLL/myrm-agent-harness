"""Tests for orphan matching rules: automation cache path / driver cmdline recognition and python-ancestry walk."""

from __future__ import annotations

import os
from unittest.mock import create_autospec, patch

import psutil
import pytest

from myrm_agent_harness.toolkits.browser.doctor.orphans import (
    _extract_user_data_dir,
    _has_python_ancestor,
    _is_automation_cache_path,
    _is_automation_driver_cmdline,
)


def test_extract_user_data_dir_with_equals() -> None:
    """Should extract user-data-dir with = syntax."""
    cmdline = "/usr/bin/chrome --user-data-dir=/tmp/playwright_chromium --headless"
    result = _extract_user_data_dir(cmdline)
    assert result == "/tmp/playwright_chromium"


def test_extract_user_data_dir_without_equals() -> None:
    """Should extract user-data-dir with space syntax."""
    cmdline = "/usr/bin/chrome --user-data-dir /tmp/playwright_chromium --headless"
    result = _extract_user_data_dir(cmdline)
    assert result == "/tmp/playwright_chromium"


def test_extract_user_data_dir_missing() -> None:
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
        ("/private/var/folders/sf/cw/X/com.google.Chrome.code_sign_clone", True),
        ("/tmp/chrome_e2e_profile", True),
        ("/home/user/.config/google-chrome", False),
        ("/tmp/selenium_chrome", False),
        ("/Applications/Google Chrome.app", False),
    ],
)
def test_is_automation_cache_path(path: str, expected: bool) -> None:
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
def test_is_automation_driver_cmdline(cmdline: str, expected: bool) -> None:
    assert _is_automation_driver_cmdline(cmdline) is expected


def test_has_python_ancestor_matches_current_tree() -> None:
    """Should flag a process whose parent is inside the current process tree."""
    proc = create_autospec(psutil.Process)
    parent = create_autospec(psutil.Process)
    parent.pid = os.getpid()
    parent.name.return_value = "node"
    parent.parent.return_value = None
    proc.parent.return_value = parent

    assert _has_python_ancestor(proc, os.getpid()) is True


def test_has_python_ancestor_matches_python_parent() -> None:
    """Should flag a process whose parent chain contains a python process."""
    proc = create_autospec(psutil.Process)
    parent = create_autospec(psutil.Process)
    parent.pid = 9999
    parent.name.return_value = "python3.13"
    parent.parent.return_value = None
    proc.parent.return_value = parent

    assert _has_python_ancestor(proc, os.getpid()) is True


def test_has_python_ancestor_returns_false_when_chain_ends() -> None:
    """Should return False when the parent chain has no python or tree match."""
    proc = create_autospec(psutil.Process)
    leaf = create_autospec(psutil.Process)
    leaf.pid = 9998
    leaf.name.return_value = "node"
    leaf.parent.return_value = None
    proc.parent.return_value = leaf

    assert _has_python_ancestor(proc, os.getpid()) is False


def test_has_python_ancestor_tolerates_unexpected_error() -> None:
    """Should conservatively flag the process when the walk raises unexpectedly."""
    proc = create_autospec(psutil.Process)
    proc.parent.side_effect = RuntimeError("boom")

    assert _has_python_ancestor(proc, os.getpid()) is True


def test_has_python_ancestor_breaks_when_parent_name_denied() -> None:
    """Should stop walking when a parent's name cannot be read."""
    proc = create_autospec(psutil.Process)
    parent = create_autospec(psutil.Process)
    parent.pid = 9997
    parent.name.side_effect = psutil.AccessDenied()
    parent.parent.return_value = None
    proc.parent.return_value = parent

    assert _has_python_ancestor(proc, os.getpid()) is False


def test_has_python_ancestor_breaks_when_parent_walk_denied() -> None:
    """Should stop walking when reaching a parent raises AccessDenied."""
    proc = create_autospec(psutil.Process)
    parent = create_autospec(psutil.Process)
    parent.pid = 9996
    parent.name.return_value = "node"
    parent.parent.side_effect = psutil.AccessDenied()
    proc.parent.return_value = parent

    assert _has_python_ancestor(proc, os.getpid()) is False


def test_has_python_ancestor_returns_false_when_current_proc_gone() -> None:
    """Should return False when the current process itself is gone."""
    proc = create_autospec(psutil.Process)

    with patch("psutil.Process", side_effect=psutil.NoSuchProcess(999)):
        assert _has_python_ancestor(proc, os.getpid()) is False
