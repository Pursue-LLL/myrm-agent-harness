"""Ownership stamp: what a launched browser carries and how a process is classified by it."""

from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import psutil
import pytest

from myrm_agent_harness.toolkits.browser import process_owner
from myrm_agent_harness.toolkits.browser.process_owner import (
    OWNER_ENV_VAR,
    OwnerState,
    owner_stamp_env,
    read_owner_state,
)
from tests.toolkits.browser._stamped_processes import StampedProcesses, dead_owner_stamp, live_owner_stamp


def test_owner_stamp_env_names_this_process_by_pid_and_start_time() -> None:
    stamp = owner_stamp_env()[OWNER_ENV_VAR]

    pid_text, start_text = stamp.split(":")
    assert int(pid_text) == os.getpid()
    assert abs(int(start_text) - int(psutil.Process().create_time() * 1000)) <= 1


def test_owner_stamp_env_is_empty_without_psutil() -> None:
    with patch.dict(sys.modules, {"psutil": None}):
        assert owner_stamp_env() == {}


def test_process_without_stamp_is_unstamped(stamped_processes: StampedProcesses) -> None:
    child = stamped_processes.spawn(None)

    assert read_owner_state(psutil.Process(child.pid)) is OwnerState.UNSTAMPED


def test_process_stamped_by_a_running_owner_is_owner_alive(stamped_processes: StampedProcesses) -> None:
    child = stamped_processes.spawn(live_owner_stamp())

    assert read_owner_state(psutil.Process(child.pid)) is OwnerState.OWNER_ALIVE


def test_process_stamped_by_an_exited_owner_is_owner_gone(stamped_processes: StampedProcesses) -> None:
    child = stamped_processes.spawn(dead_owner_stamp())

    assert read_owner_state(psutil.Process(child.pid)) is OwnerState.OWNER_GONE


def test_reused_pid_with_another_start_time_is_owner_gone(stamped_processes: StampedProcesses) -> None:
    """A live process that merely holds the owner's old pid is not the owner."""
    hour_earlier_ms = int(psutil.Process().create_time() * 1000) - 3_600_000
    child = stamped_processes.spawn(f"{os.getpid()}:{hour_earlier_ms}")

    assert read_owner_state(psutil.Process(child.pid)) is OwnerState.OWNER_GONE


@pytest.mark.skipif(sys.platform == "win32", reason="a defunct process needs POSIX wait semantics")
def test_owner_that_is_a_zombie_counts_as_gone(stamped_processes: StampedProcesses) -> None:
    """An exited owner that nobody has reaped yet still holds its pid but is no longer running."""
    owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.3)"])
    stamp = f"{owner.pid}:{int(psutil.Process(owner.pid).create_time() * 1000)}"
    os.waitid(os.P_PID, owner.pid, os.WEXITED | os.WNOWAIT)
    try:
        assert psutil.Process(owner.pid).status() == psutil.STATUS_ZOMBIE
        child = stamped_processes.spawn(stamp)

        assert read_owner_state(psutil.Process(child.pid)) is OwnerState.OWNER_GONE
    finally:
        owner.wait()


@pytest.mark.parametrize("stamp", ["garbage", "abc:def", "12345", "", "-1:5", "1:2:3", "0:1000", ":"])
def test_malformed_stamp_is_unknown(stamped_processes: StampedProcesses, stamp: str) -> None:
    """A stamp that cannot be parsed names no owner, so the process must never be treated as a leftover."""
    child = stamped_processes.spawn(stamp)

    assert read_owner_state(psutil.Process(child.pid)) is OwnerState.UNKNOWN


@pytest.mark.parametrize(
    "error",
    [
        psutil.AccessDenied(1),
        psutil.NoSuchProcess(1),
        OSError("denied"),
        SystemError("<built-in function proc_environ> returned a result with an exception set"),
    ],
    ids=["access-denied", "no-such-process", "os-error", "psutil-macos-system-error"],
)
def test_unreadable_environment_is_unknown(error: Exception) -> None:
    proc = MagicMock(spec=psutil.Process)
    proc.environ.side_effect = error

    assert read_owner_state(proc) is OwnerState.UNKNOWN


def test_owner_that_cannot_be_inspected_is_unknown(stamped_processes: StampedProcesses) -> None:
    child = stamped_processes.spawn(live_owner_stamp())
    victim = psutil.Process(child.pid)

    with patch("psutil.Process.create_time", side_effect=psutil.AccessDenied(os.getpid())):
        assert read_owner_state(victim) is OwnerState.UNKNOWN


def test_stamp_survives_a_wall_clock_second_of_slack(stamped_processes: StampedProcesses) -> None:
    """psutil derives start times per platform; sub-second drift must not turn a live owner into a leftover."""
    now_ms = int(psutil.Process().create_time() * 1000)
    child = stamped_processes.spawn(f"{os.getpid()}:{now_ms + 400}")

    assert read_owner_state(psutil.Process(child.pid)) is OwnerState.OWNER_ALIVE


def test_stamp_survives_a_system_clock_jump_where_start_times_follow_the_wall_clock(
    stamped_processes: StampedProcesses, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Linux derives a start time as boot time plus ticks, so a clock step must not make a live owner look gone."""
    boot_time = [1_700_000_000.0]
    ticks_since_boot = 5_000.0
    monkeypatch.setattr(psutil, "boot_time", lambda: boot_time[0])
    monkeypatch.setattr(psutil.Process, "create_time", lambda self: ticks_since_boot + boot_time[0])
    monkeypatch.setattr(process_owner, "_START_TIMES_FOLLOW_WALL_CLOCK", True)
    stamp = owner_stamp_env()[OWNER_ENV_VAR]
    child = stamped_processes.spawn(stamp)

    boot_time[0] += 600.0  # e.g. a VM resumed with a corrected clock

    assert read_owner_state(psutil.Process(child.pid)) is OwnerState.OWNER_ALIVE
