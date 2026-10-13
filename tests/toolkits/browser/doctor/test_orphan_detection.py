"""Orphan detection: a leftover is a Chromium process that carries the stamp of an owner that is gone."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil
import pytest

import myrm_agent_harness
from myrm_agent_harness.toolkits.browser.doctor import find_orphan_automation_processes
from myrm_agent_harness.toolkits.browser.doctor.orphans import _extract_user_data_dir, _is_chromium_process
from myrm_agent_harness.toolkits.browser.process_owner import OWNER_ENV_VAR
from tests.toolkits.browser._stamped_processes import StampedProcesses, dead_owner_stamp, live_owner_stamp

# Command lines that look exactly like a Playwright browser of some other tool.
_FOREIGN_PLAYWRIGHT_ARGS = ("--user-data-dir=/home/user/.cache/ms-playwright/chromium-1208", "--headless")
_PROFILE_WITH_SPACES = "/Users/a b/Library/Chrome Profile"


def _reported_pids() -> set[int]:
    return {orphan["pid"] for orphan in find_orphan_automation_processes()}


def test_process_stamped_by_a_gone_owner_is_reported(stamped_processes: StampedProcesses) -> None:
    profile = "/tmp/playwright_chromiumdev_profile-leftover"
    child = stamped_processes.spawn(dead_owner_stamp(), extra_args=(f"--user-data-dir={profile}",))

    orphans = [o for o in find_orphan_automation_processes() if o["pid"] == child.pid]

    assert len(orphans) == 1
    assert orphans[0]["ppid"] == os.getpid()
    assert orphans[0]["name"]
    assert orphans[0]["user_data_dir"] == profile


def test_process_without_stamp_is_never_reported_whatever_it_looks_like(stamped_processes: StampedProcesses) -> None:
    """Another tool's browser, launched from any shell and still running, must not be mistaken for a leftover."""
    foreign = stamped_processes.spawn(None, extra_args=_FOREIGN_PLAYWRIGHT_ARGS)

    assert foreign.pid not in _reported_pids()


def test_process_whose_owner_is_alive_is_not_reported(stamped_processes: StampedProcesses) -> None:
    running = stamped_processes.spawn(live_owner_stamp())

    assert running.pid not in _reported_pids()


@pytest.mark.parametrize("stamp", ["garbage", "abc:def", "0:1000", ""])
def test_process_with_malformed_stamp_is_not_reported(stamped_processes: StampedProcesses, stamp: str) -> None:
    child = stamped_processes.spawn(stamp)

    assert child.pid not in _reported_pids()


def test_only_the_stamped_leftover_is_reported_among_bystanders(stamped_processes: StampedProcesses) -> None:
    leftover = stamped_processes.spawn(dead_owner_stamp())
    bystanders = [
        stamped_processes.spawn(None, extra_args=_FOREIGN_PLAYWRIGHT_ARGS),
        stamped_processes.spawn(live_owner_stamp()),
        stamped_processes.spawn("garbage"),
        stamped_processes.spawn(dead_owner_stamp(), browser=False),
    ]
    spawned = {leftover.pid, *(child.pid for child in bystanders)}

    assert _reported_pids() & spawned == {leftover.pid}


def test_stamped_process_that_is_not_a_browser_is_never_reported(stamped_processes: StampedProcesses) -> None:
    """An application a browser opened and that inherited the stamp of its owner is not a leftover browser."""
    application = stamped_processes.spawn(dead_owner_stamp(), browser=False)

    assert application.pid not in _reported_pids()


def test_process_running_the_scan_never_reports_itself(stamped_processes: StampedProcesses) -> None:
    """A scanning Chromium process that inherited a stamp of a gone owner must not list, and so never kill, itself."""
    src_root = Path(myrm_agent_harness.__file__).resolve().parents[1]
    scan = (
        "import json, os\n"
        "from myrm_agent_harness.toolkits.browser.doctor import find_orphan_automation_processes\n"
        "print(json.dumps({'me': os.getpid(), 'found': [o['pid'] for o in find_orphan_automation_processes()]}))\n"
    )
    # The stand-in executable lives outside the virtual environment, so it gets the parent's import path.
    import_path = os.pathsep.join([str(src_root), *filter(None, sys.path)])
    env = {**os.environ, OWNER_ENV_VAR: dead_owner_stamp(), "PYTHONPATH": import_path}

    result = subprocess.run(
        [str(stamped_processes.browser_executable), "-c", scan], env=env, capture_output=True, text=True, check=True
    )
    outcome = json.loads(result.stdout)

    assert outcome["me"] not in outcome["found"]


def test_scan_skips_a_process_that_vanishes_mid_scan(stamped_processes: StampedProcesses) -> None:
    vanished = MagicMock(spec=psutil.Process)
    vanished.environ.side_effect = psutil.NoSuchProcess(99999)
    leftover = stamped_processes.spawn(dead_owner_stamp())

    with patch("psutil.process_iter", return_value=[vanished, psutil.Process(leftover.pid)]):
        orphans = find_orphan_automation_processes()

    assert [o["pid"] for o in orphans] == [leftover.pid]


def test_scan_reports_nothing_without_psutil() -> None:
    with patch.dict(sys.modules, {"psutil": None}):
        assert find_orphan_automation_processes() == []


def test_scan_failure_is_logged_and_reports_nothing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING), patch("psutil.process_iter", side_effect=RuntimeError("scan failed")):
        assert find_orphan_automation_processes() == []

    assert "scan failed" in caplog.text


def _described(name: str, exe: str, argv: list[str]) -> MagicMock:
    """A process as the three identity sources report it; a platform quirk cannot be reproduced with a real one."""
    proc = MagicMock(spec=psutil.Process)
    proc.name.return_value = name
    proc.exe.return_value = exe
    proc.cmdline.return_value = argv
    return proc


@pytest.mark.parametrize(
    ("name", "exe", "argv"),
    [
        pytest.param("chrome-headless-shell", "/x/launcher", ["launcher"], id="name"),
        pytest.param("exe", "/x/chromium-1243/chrome", ["exe", "--type=zygote"], id="executable"),
        pytest.param("exe", "/x/launcher", ["/x/Chromium.app/Contents/MacOS/Chromium"], id="argv0"),
    ],
)
def test_any_one_source_naming_chromium_identifies_a_browser(name: str, exe: str, argv: list[str]) -> None:
    assert _is_chromium_process(_described(name, exe, argv))


@pytest.mark.parametrize(
    ("name", "exe", "argv"),
    [
        pytest.param("xdg-email", "/usr/bin/xdg-email", ["xdg-email", "mailto:a@example.com"], id="mail-handler"),
        pytest.param(
            "evince",
            "/home/u/chromium-profile/evince",
            ["evince", "--user-data-dir=/x/chromium"],
            id="chromium-only-in-a-directory-or-an-argument",
        ),
        pytest.param("python3.13", "/usr/bin/python3.13", [], id="empty-command-line"),
    ],
)
def test_process_that_does_not_run_a_chromium_binary_is_not_a_browser(name: str, exe: str, argv: list[str]) -> None:
    assert not _is_chromium_process(_described(name, exe, argv))


def test_unreadable_source_does_not_hide_the_others() -> None:
    proc = _described("chrome", "/x/chrome", ["chrome"])
    proc.exe.side_effect = psutil.AccessDenied(1)
    proc.cmdline.side_effect = psutil.NoSuchProcess(1)

    assert _is_chromium_process(proc)


def test_process_with_no_readable_source_is_not_a_browser() -> None:
    proc = MagicMock(spec=psutil.Process)
    for read in (proc.name, proc.exe, proc.cmdline):
        read.side_effect = psutil.AccessDenied(1)

    assert not _is_chromium_process(proc)


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["/usr/bin/chrome", "--user-data-dir=/tmp/playwright_chromium", "--headless"], "/tmp/playwright_chromium"),
        (["/usr/bin/chrome", "--user-data-dir", "/tmp/playwright_chromium", "--headless"], "/tmp/playwright_chromium"),
        (["/usr/bin/chrome", f"--user-data-dir={_PROFILE_WITH_SPACES}"], _PROFILE_WITH_SPACES),
        (["/usr/bin/chrome", "--user-data-dir", _PROFILE_WITH_SPACES], _PROFILE_WITH_SPACES),
        (["/usr/bin/chrome", "--user-data-dir-extra=/tmp/other", "--headless"], ""),
        (["/usr/bin/chrome", "--headless", "--no-sandbox"], ""),
        (["/usr/bin/chrome", "--user-data-dir="], ""),
        (["/usr/bin/chrome", "--user-data-dir"], ""),
    ],
)
def test_user_data_dir_is_read_from_either_flag_syntax(args: list[str], expected: str) -> None:
    assert _extract_user_data_dir(args) == expected
