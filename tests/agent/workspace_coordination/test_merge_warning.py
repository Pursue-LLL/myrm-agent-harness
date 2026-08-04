"""Tests for per-turn workspace merge warning tracker."""

from __future__ import annotations

from myrm_agent_harness.agent.workspace_coordination.merge_warning import (
    format_workspace_merge_failures,
    has_workspace_merge_warning,
    record_workspace_merge_failure,
    reset_workspace_merge_warning,
)


def test_merge_warning_lifecycle() -> None:
    reset_workspace_merge_warning()
    assert has_workspace_merge_warning() is False
    assert format_workspace_merge_failures() is None

    record_workspace_merge_failure("task_a: disk full")
    assert has_workspace_merge_warning() is True
    payload = format_workspace_merge_failures()
    assert payload is not None
    assert payload["failed_count"] == 1
    assert payload["errors"] == [{"message": "task_a: disk full"}]

    reset_workspace_merge_warning()
    assert has_workspace_merge_warning() is False


def test_merge_warning_skips_blank_messages() -> None:
    reset_workspace_merge_warning()
    record_workspace_merge_failure("   ")
    assert has_workspace_merge_warning() is False


def test_merge_warning_truncated_payload() -> None:
    reset_workspace_merge_warning()
    for index in range(12):
        record_workspace_merge_failure(f"task_index={index}: boom")
    payload = format_workspace_merge_failures()
    assert payload is not None
    assert payload["failed_count"] == 12
    assert len(payload["errors"]) == 10
    assert payload["truncated"] == 2
