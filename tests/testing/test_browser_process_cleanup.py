"""Tests for shipped pytest teardown helpers."""

from __future__ import annotations

from unittest.mock import patch

from myrm_agent_harness.testing import browser_process_cleanup as bpc


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
