"""Tests for pytest browser process-tree teardown helpers."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from tests.support import browser_process_cleanup as bpc


def test_terminate_browser_processes_in_tree_skips_non_automation_descendants() -> None:
    rows = [
        (1000, 1, "python -m pytest"),
        (1001, 1000, "sleep 10"),
    ]
    terminated: list[int] = []

    with (
        patch.object(bpc, "_list_process_rows", return_value=rows),
        patch.object(bpc, "terminate_process_graceful", side_effect=terminated.append),
    ):
        count = bpc.terminate_browser_processes_in_tree(1000)

    assert count == 0
    assert terminated == []


def test_terminate_browser_processes_in_tree_terminates_automation_descendants() -> None:
    rows = [
        (1000, 1, "python -m pytest"),
        (1001, 1000, "patchright/driver/node run-driver"),
        (1002, 1000, "sleep 10"),
        (1003, 1001, "Google Chrome for Testing --headless"),
    ]
    terminated: list[int] = []

    with (
        patch.object(bpc, "_list_process_rows", return_value=rows),
        patch.object(bpc, "terminate_process_graceful", side_effect=terminated.append),
    ):
        count = bpc.terminate_browser_processes_in_tree(1000)

    assert count == 2
    assert terminated == [1001, 1003]


def test_terminate_browser_processes_in_tree_uses_current_pid_when_root_unset() -> None:
    rows: list[tuple[int, int, str]] = []

    with (
        patch.object(bpc.os, "getpid", return_value=4242),
        patch.object(bpc, "_list_process_rows", return_value=rows),
        patch.object(bpc, "_descendant_pids", return_value=set()) as mock_descendants,
    ):
        count = bpc.terminate_browser_processes_in_tree()

    mock_descendants.assert_called_once_with(4242, rows)
    assert count == 0


def test_terminate_browser_processes_in_tree_logs_permission_error() -> None:
    rows = [
        (1000, 1, "python -m pytest"),
        (1001, 1000, "playwright/driver/node run-driver"),
    ]

    with (
        patch.object(bpc, "_list_process_rows", return_value=rows),
        patch.object(bpc, "terminate_process_graceful", side_effect=PermissionError),
        patch.object(bpc.logger, "warning") as mock_warning,
    ):
        count = bpc.terminate_browser_processes_in_tree(1000)

    assert count == 0
    mock_warning.assert_called_once_with("Permission denied terminating automation pid=%s", 1001)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("chrome-headless-shell --foo", True),
        ("puppeteer/chrome/linux", True),
        ("run-driver", True),
        ("sleep 10", False),
    ],
)
def test_is_automation_command(command: str, expected: bool) -> None:
    assert bpc._is_automation_command(command) is expected


def test_descendant_pids_includes_nested_children() -> None:
    rows = [
        (1000, 1, "pytest"),
        (1001, 1000, "driver"),
        (1002, 1001, "chrome"),
    ]

    assert bpc._descendant_pids(1000, rows) == {1001, 1002}


def test_descendant_pids_skips_revisited_nodes() -> None:
    rows = [
        (1000, 1, "pytest"),
        (1001, 1000, "a"),
        (1002, 1000, "b"),
        (1003, 1001, "c"),
    ]

    assert bpc._descendant_pids(1000, rows) == {1001, 1002, 1003}


def test_list_process_rows_parses_ps_output() -> None:
    completed = subprocess.CompletedProcess(
        args=["ps"],
        returncode=0,
        stdout=" 1000 1 python -m pytest\n\n 1001 1000 patchright/driver/node\n 1002 1000\n malformed-line\n",
        stderr="",
    )

    with patch.object(bpc.subprocess, "run", return_value=completed) as mock_run:
        rows = bpc._list_process_rows()

    mock_run.assert_called_once()
    assert rows == [
        (1000, 1, "python -m pytest"),
        (1001, 1000, "patchright/driver/node"),
        (1002, 1000, ""),
    ]


def test_descendant_pids_breaks_cycle() -> None:
    rows = [
        (1000, 1, "pytest"),
        (1001, 1000, "a"),
        (1002, 1001, "b"),
        (1001, 1002, "cycle"),
    ]

    assert bpc._descendant_pids(1000, rows) == {1001, 1002}
