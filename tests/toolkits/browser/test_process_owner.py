"""Ownership stamp: what a launched browser carries and how a process is classified by it."""

from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import psutil
import pytest

from myrm_agent_harness.toolkits.browser.process_owner import (
    OWNER_ENV_VAR,
    OwnerState,
    owner_stamp_env,
    owner_stamped_environ,
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


def test_stamped_environ_exposes_the_stamp_only_inside_the_block() -> None:
    assert OWNER_ENV_VAR not in os.environ

    with owner_stamped_environ():
        assert os.environ[OWNER_ENV_VAR] == owner_stamp_env()[OWNER_ENV_VAR]

    assert OWNER_ENV_VAR not in os.environ


def test_stamped_environ_is_removed_when_the_block_raises() -> None:
    with pytest.raises(RuntimeError), owner_stamped_environ():
        raise RuntimeError("driver failed to start")

    assert OWNER_ENV_VAR not in os.environ


def test_stamped_environ_does_not_reach_processes_started_afterwards() -> None:
    with owner_stamped_environ():
        pass

    out = subprocess.run(
        [sys.executable, "-c", f"import os; print(os.environ.get({OWNER_ENV_VAR!r}))"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert out == "None"


def test_stamped_environ_reaches_a_driver_started_inside_the_block() -> None:
    with owner_stamped_environ():
        out = subprocess.run(
            [sys.executable, "-c", f"import os; print(os.environ.get({OWNER_ENV_VAR!r}))"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    assert out == owner_stamp_env()[OWNER_ENV_VAR]


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


@pytest.mark.parametrize("error", [psutil.AccessDenied(1), psutil.NoSuchProcess(1), OSError("denied")])
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
