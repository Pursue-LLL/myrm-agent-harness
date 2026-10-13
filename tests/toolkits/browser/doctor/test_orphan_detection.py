"""Orphan detection: a process is a leftover only when it carries the stamp of an owner that is gone."""

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
from myrm_agent_harness.toolkits.browser.doctor.orphans import _extract_user_data_dir
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
    ]
    spawned = {leftover.pid, *(child.pid for child in bystanders)}

    assert _reported_pids() & spawned == {leftover.pid}


def test_process_running_the_scan_never_reports_itself(stamped_processes: StampedProcesses) -> None:
    """A scanning process that inherited a stamp of a gone owner must not list, and so never kill, itself."""
    src_root = Path(myrm_agent_harness.__file__).resolve().parents[1]
    scan = (
        "import json, os\n"
        "from myrm_agent_harness.toolkits.browser.doctor import find_orphan_automation_processes\n"
        "print(json.dumps({'me': os.getpid(), 'found': [o['pid'] for o in find_orphan_automation_processes()]}))\n"
    )
    env = {**os.environ, OWNER_ENV_VAR: dead_owner_stamp(), "PYTHONPATH": str(src_root)}

    result = subprocess.run([sys.executable, "-c", scan], env=env, capture_output=True, text=True, check=True)
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
