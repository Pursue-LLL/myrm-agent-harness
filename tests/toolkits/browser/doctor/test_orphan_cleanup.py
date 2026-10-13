"""Orphan cleanup: only a verified leftover is ever signalled, and a stubborn one is escalated to SIGKILL."""

from __future__ import annotations

import sys
from unittest.mock import patch

from myrm_agent_harness.toolkits.browser.doctor import (
    CheckStatus,
    check_orphan_processes,
    cleanup_orphan_processes,
)
from tests.toolkits.browser._stamped_processes import StampedProcesses, dead_owner_stamp, live_owner_stamp

_ORPHANS = "myrm_agent_harness.toolkits.browser.doctor.orphans"


def test_dry_run_is_the_default_and_signals_nothing(stamped_processes: StampedProcesses) -> None:
    leftover = stamped_processes.spawn(dead_owner_stamp())

    result = cleanup_orphan_processes([leftover.pid, 67890])

    assert result["dry_run"] is True
    assert result["killed"] == 0
    assert result["would_kill"] == 2
    assert "Dry-run" in result["message"]
    assert leftover.poll() is None


def test_force_terminates_a_verified_leftover(stamped_processes: StampedProcesses) -> None:
    leftover = stamped_processes.spawn(dead_owner_stamp())

    result = cleanup_orphan_processes([leftover.pid], force=True)

    assert result["dry_run"] is False
    assert result["killed"] == 1
    assert result["failed"] == []
    assert stamped_processes.wait_gone(leftover)


def test_force_refuses_a_process_without_stamp(stamped_processes: StampedProcesses) -> None:
    """A pid that no longer (or never did) belong to a leftover, e.g. after pid reuse, is left alone."""
    foreign = stamped_processes.spawn(None)

    result = cleanup_orphan_processes([foreign.pid], force=True)

    assert result["killed"] == 0
    assert result["failed"] == [{"pid": foreign.pid, "reason": "not_an_orphan"}]
    assert foreign.poll() is None


def test_force_refuses_a_process_whose_owner_is_alive(stamped_processes: StampedProcesses) -> None:
    running = stamped_processes.spawn(live_owner_stamp())

    result = cleanup_orphan_processes([running.pid], force=True)

    assert result["killed"] == 0
    assert result["failed"] == [{"pid": running.pid, "reason": "not_an_orphan"}]
    assert running.poll() is None


def test_force_ignores_a_pid_that_already_exited(stamped_processes: StampedProcesses) -> None:
    child = stamped_processes.spawn(dead_owner_stamp())
    child.kill()
    child.wait()

    result = cleanup_orphan_processes([child.pid], force=True)

    assert result["killed"] == 0
    assert result["failed"] == []


def test_auto_detect_terminates_leftovers_and_spares_everything_else(stamped_processes: StampedProcesses) -> None:
    leftover = stamped_processes.spawn(dead_owner_stamp())
    foreign = stamped_processes.spawn(None, extra_args=("--user-data-dir=/home/u/.cache/ms-playwright/chromium-1",))
    running = stamped_processes.spawn(live_owner_stamp())

    result = cleanup_orphan_processes(force=True)

    assert result["killed"] >= 1
    assert stamped_processes.wait_gone(leftover)
    assert foreign.poll() is None
    assert running.poll() is None


def test_stubborn_leftover_is_escalated_to_sigkill(stamped_processes: StampedProcesses) -> None:
    """A process that ignores SIGTERM, as a hung renderer does, must still be removed within the grace period."""
    stubborn = stamped_processes.spawn(dead_owner_stamp(), ignore_sigterm=True)

    result = cleanup_orphan_processes([stubborn.pid], force=True, timeout_s=2.0)

    assert result["killed"] == 1
    assert stamped_processes.wait_gone(stubborn)


def test_without_grace_period_a_stubborn_leftover_only_gets_sigterm(stamped_processes: StampedProcesses) -> None:
    stubborn = stamped_processes.spawn(dead_owner_stamp(), ignore_sigterm=True)

    result = cleanup_orphan_processes([stubborn.pid], force=True)

    assert result["killed"] == 1
    assert stubborn.poll() is None


def test_leftover_that_survives_sigkill_is_reported_as_failed(stamped_processes: StampedProcesses) -> None:
    leftover = stamped_processes.spawn(dead_owner_stamp())

    with patch("os.kill"), patch(f"{_ORPHANS}._SIGKILL_SETTLE_S", 0.05):
        result = cleanup_orphan_processes([leftover.pid], force=True, timeout_s=0.1)

    assert result["killed"] == 0
    assert result["failed"] == [{"pid": leftover.pid, "reason": "process_still_running_after_kill"}]


def test_process_that_exits_between_check_and_signal_is_not_a_failure(stamped_processes: StampedProcesses) -> None:
    leftover = stamped_processes.spawn(dead_owner_stamp())

    with patch("os.kill", side_effect=ProcessLookupError):
        result = cleanup_orphan_processes([leftover.pid], force=True)

    assert result["killed"] == 0
    assert result["dry_run"] is False
    assert result["failed"] == []


def test_permission_denied_is_recorded(stamped_processes: StampedProcesses) -> None:
    leftover = stamped_processes.spawn(dead_owner_stamp())

    with patch("os.kill", side_effect=PermissionError):
        result = cleanup_orphan_processes([leftover.pid], force=True)

    assert result["killed"] == 0
    assert result["failed"] == [{"pid": leftover.pid, "reason": "permission_denied"}]


def test_unexpected_signal_failure_is_recorded_with_its_reason(stamped_processes: StampedProcesses) -> None:
    leftover = stamped_processes.spawn(dead_owner_stamp())

    with patch("os.kill", side_effect=RuntimeError("signal failed")):
        result = cleanup_orphan_processes([leftover.pid], force=True)

    assert result["killed"] == 0
    assert result["failed"] == [{"pid": leftover.pid, "reason": "signal failed"}]


def test_cleanup_without_psutil_reports_an_error() -> None:
    with patch.dict(sys.modules, {"psutil": None}):
        result = cleanup_orphan_processes([12345], force=True)

    assert result["dry_run"] is True
    assert result["killed"] == 0
    assert result["error"] == "psutil not available"


def test_check_orphan_processes_previews_only_first_pids() -> None:
    """Should preview only the first three pids when many orphans exist."""
    orphans = [{"pid": pid, "name": "chrome", "ppid": 1, "user_data_dir": "/tmp/x"} for pid in (1111, 2222, 3333, 4444)]

    with (
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.orphan_check.find_orphan_automation_processes",
            return_value=orphans,
        ),
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.orphan_check.cleanup_stale_automation_sandboxes",
            return_value={"pruned": 0, "reclaimed_bytes": 0},
        ),
    ):
        result = check_orphan_processes()

    assert result.status == CheckStatus.WARNING
    assert "4 orphan automation" in result.message
    assert "..." in result.message
    assert result.details == {
        "count": 4,
        "pids": [1111, 2222, 3333, 4444],
        "paths": ["/tmp/x", "/tmp/x", "/tmp/x", "/tmp/x"],
        "stale_sandboxes": 0,
        "stale_sandbox_bytes": 0,
    }


def test_check_orphan_processes_reports_stale_sandboxes_when_no_orphans() -> None:
    """Should report WARNING when no orphan processes exist but stale sandboxes are detected."""
    with (
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.orphan_check.find_orphan_automation_processes",
            return_value=[],
        ),
        patch(
            "myrm_agent_harness.toolkits.browser.doctor.orphan_check.cleanup_stale_automation_sandboxes",
            return_value={"pruned": 3, "reclaimed_bytes": 104857600},
        ),
    ):
        result = check_orphan_processes()

    assert result.status == CheckStatus.WARNING
    assert "3 stale sandbox(es) (100.0 MB)" in result.message
    assert result.details is not None
    assert result.details["count"] == 0
    assert result.details["stale_sandboxes"] == 3
    assert result.details["stale_sandbox_bytes"] == 104857600
