"""Tests for orphan process cleanup, the exit reaper, and the orphan doctor check adapter."""

from __future__ import annotations

import os
import signal
import sys
from unittest.mock import MagicMock, patch

from myrm_agent_harness.toolkits.browser.doctor import (
    CheckStatus,
    check_orphan_processes,
    cleanup_orphan_processes,
    register_browser_exit_reaper,
    unregister_browser_exit_reaper,
)
from myrm_agent_harness.toolkits.browser.doctor.orphans import (
    _emergency_cleanup_orphans_on_exit,
)


def test_cleanup_orphan_processes_dry_run_default() -> None:
    """Should not kill processes when force=False (dry-run)."""
    result = cleanup_orphan_processes([12345, 67890], force=False)

    assert result["dry_run"] is True
    assert result["killed"] == 0
    assert result["would_kill"] == 2
    assert "Dry-run" in result["message"]


def test_cleanup_orphan_processes_with_force() -> None:
    """Should kill processes when force=True."""
    with patch("os.kill") as mock_kill:
        result = cleanup_orphan_processes([12345], force=True)

        assert result["dry_run"] is False
        assert result["killed"] == 1
        mock_kill.assert_called_once()


def test_cleanup_orphan_processes_handles_process_not_found() -> None:
    """Should handle ProcessLookupError gracefully."""
    with patch("os.kill", side_effect=ProcessLookupError):
        result = cleanup_orphan_processes([12345], force=True)

        assert result["killed"] == 0
        assert result["dry_run"] is False


def test_cleanup_orphan_processes_handles_permission_error() -> None:
    """Should record permission failures."""
    with patch("os.kill", side_effect=PermissionError):
        result = cleanup_orphan_processes([12345], force=True)

        assert result["killed"] == 0
        assert len(result["failed"]) == 1
        assert result["failed"][0]["reason"] == "permission_denied"


def test_cleanup_orphan_processes_psutil_missing() -> None:
    """Should return error when psutil unavailable."""
    with patch.dict(sys.modules, {"psutil": None}):
        result = cleanup_orphan_processes([12345], force=True)

        assert result["dry_run"] is True
        assert result["killed"] == 0
        assert result["error"] == "psutil not available"


def test_cleanup_orphan_processes_auto_detect() -> None:
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


def test_cleanup_orphan_processes_handles_generic_exception() -> None:
    """Should record any unexpected kill failure with its reason."""
    with patch("os.kill", side_effect=RuntimeError("signal failed")):
        result = cleanup_orphan_processes([12345], force=True)

        assert result["killed"] == 0
        assert result["failed"] == [{"pid": 12345, "reason": "signal failed"}]


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


def test_cleanup_orphan_processes_escalates_to_sigkill() -> None:
    """Should escalate to SIGKILL when process does not terminate within timeout_s."""
    call_log: list[tuple[int, int]] = []

    def mock_kill(pid: int, sig: int) -> None:
        call_log.append((pid, sig))
        # After SIGKILL is sent, the next os.kill(pid, 0) probe should report process is gone
        if sig == 0 and any(s == signal.SIGKILL for (_, s) in call_log):
            raise ProcessLookupError()

    with patch("os.kill", side_effect=mock_kill):
        result = cleanup_orphan_processes([54321], force=True, timeout_s=0.1)

        assert result["dry_run"] is False
        assert result["killed"] == 1
        signals_sent = [sig for (_, sig) in call_log]
        assert signal.SIGTERM in signals_sent
        assert signal.SIGKILL in signals_sent


def test_register_and_unregister_browser_exit_reaper() -> None:
    """Should register and unregister atexit hook idempotently, respecting env disable."""
    unregister_browser_exit_reaper()

    # First register should succeed
    assert register_browser_exit_reaper() is True
    # Second register should be idempotent (return False)
    assert register_browser_exit_reaper() is False

    # Unregister should succeed
    assert unregister_browser_exit_reaper() is True
    assert unregister_browser_exit_reaper() is False

    # Test disabled via environment variable
    with (
        patch.dict(os.environ, {"MYRM_BROWSER_EXIT_REAP_DISABLED": "1"}),
        patch("myrm_agent_harness.toolkits.browser.doctor.orphans.cleanup_orphan_processes") as mock_cleanup,
    ):
        _emergency_cleanup_orphans_on_exit()
        mock_cleanup.assert_not_called()


def test_cleanup_orphan_processes_escalation_still_running() -> None:
    """Should record failure if process remains alive after SIGKILL escalation."""
    # os.kill is called with: SIGTERM, os.kill(pid, 0) during wait (raises ProcessLookupError if dead),
    # then SIGKILL, then os.kill(pid, 0) post-kill verification.
    # Return None for all os.kill calls to simulate process never dying.
    with (
        patch("os.kill"),
        patch("time.time", side_effect=[0.0, 1.0, 2.0]),
        patch("time.sleep"),
    ):
        result = cleanup_orphan_processes([99999], force=True, timeout_s=0.1)
        assert result["killed"] == 0
        assert len(result["failed"]) == 1
        assert result["failed"][0]["reason"] == "process_still_running_after_kill"
