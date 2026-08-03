"""Unit tests for deliverable write claim verifier."""

from __future__ import annotations

from myrm_agent_harness.agent.middlewares.deliverable_write_verifier import (
    check_deliverable_write_claim,
    detect_claimed_file_write,
    has_successful_file_write_calls,
)
from myrm_agent_harness.agent.security.guards.loop_guard_types import CallRecord, SuccessLevel


def test_detect_claimed_file_write_positive() -> None:
    assert detect_claimed_file_write("Saved to `workspace/report.md`.")
    assert detect_claimed_file_write("已写入 workspace/output.csv")


def test_detect_claimed_file_write_negative() -> None:
    assert not detect_claimed_file_write("Here is the summary.")
    assert not detect_claimed_file_write("Saved your preferences.")


def test_has_successful_file_write_calls() -> None:
    records = [
        CallRecord(
            tool_name="file_write_tool",
            args_hash="h1",
            args={"path": "workspace/a.md"},
            success_level=SuccessLevel.FULL_SUCCESS,
        )
    ]
    assert has_successful_file_write_calls(records)


def test_check_deliverable_write_claim_blocks_zero_call_hallucination() -> None:
    content = "Done. Saved to `workspace/final.md`."
    reason = check_deliverable_write_claim(content, [])
    assert reason is not None
    assert "file_write_tool" in reason


def test_check_deliverable_write_claim_allows_when_write_exists() -> None:
    content = "Saved to `workspace/final.md`."
    records = [
        CallRecord(
            tool_name="file_write_tool",
            args_hash="h1",
            args={"path": "workspace/final.md"},
            success_level=SuccessLevel.FULL_SUCCESS,
        )
    ]
    assert check_deliverable_write_claim(content, records) is None
