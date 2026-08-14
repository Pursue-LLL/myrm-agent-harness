"""Unit tests for CompletionGuard deliverable write claim verifier."""

from __future__ import annotations

from myrm_agent_harness.agent.middlewares.completion.deliverable_write_verifier import (
    check_deliverable_write_claim,
    detect_claimed_file_write,
    has_successful_file_write_calls,
)
from myrm_agent_harness.agent.security.guards.loop_guard.types import (
    CallRecord,
    SuccessLevel,
)


def _record(
    tool_name: str, level: SuccessLevel = SuccessLevel.FULL_SUCCESS
) -> CallRecord:
    return CallRecord(
        tool_name=tool_name,
        args_hash="h",
        args={"path": "/workspace/x.py"},
        success_level=level,
    )


class TestDetectClaimedFileWrite:
    def test_empty_text_false(self) -> None:
        assert detect_claimed_file_write("") is False
        assert detect_claimed_file_write("   ") is False

    def test_no_claim_phrase_false(self) -> None:
        assert detect_claimed_file_write("Here is the result of the analysis.") is False

    def test_claim_phrase_without_path_false(self) -> None:
        assert detect_claimed_file_write("The file was saved.") is False

    def test_english_claim_with_backtick_path_true(self) -> None:
        assert detect_claimed_file_write("Saved to `output/report.md`.") is True

    def test_english_claim_with_workspace_path_true(self) -> None:
        assert detect_claimed_file_write("wrote to workspace/data/result.csv") is True

    def test_english_claim_with_extension_path_true(self) -> None:
        assert detect_claimed_file_write("Created the file data/report.pdf") is True

    def test_chinese_claim_true(self) -> None:
        assert detect_claimed_file_write("结果已保存到 `analysis/report.md`") is True
        assert detect_claimed_file_write("文件已生成：output/summary.xlsx") is True

    def test_case_insensitive(self) -> None:
        assert detect_claimed_file_write("WROTE TO `out.txt`") is True


class TestHasSuccessfulFileWriteCalls:
    def test_empty_records_false(self) -> None:
        assert has_successful_file_write_calls([]) is False

    def test_successful_file_write_true(self) -> None:
        assert has_successful_file_write_calls([_record("file_write_tool")]) is True

    def test_non_failure_edit_true(self) -> None:
        assert (
            has_successful_file_write_calls(
                [_record("file_edit_tool", SuccessLevel.PARTIAL_SUCCESS)]
            )
            is True
        )

    def test_failed_write_false(self) -> None:
        assert (
            has_successful_file_write_calls(
                [_record("file_write_tool", SuccessLevel.FAILURE)]
            )
            is False
        )

    def test_non_write_tool_false(self) -> None:
        assert has_successful_file_write_calls([_record("bash_code_execute_tool")]) is False

    def test_mixed_records_finds_write(self) -> None:
        records = [
            _record("bash_code_execute_tool"),
            _record("file_write_tool"),
            _record("file_edit_tool", SuccessLevel.FAILURE),
        ]
        assert has_successful_file_write_calls(records) is True


class TestCheckDeliverableWriteClaim:
    def test_no_claim_returns_none(self) -> None:
        assert check_deliverable_write_claim("Just answering.", []) is None

    def test_claim_with_successful_write_returns_none(self) -> None:
        assert (
            check_deliverable_write_claim(
                "Saved to `out/report.md`", [_record("file_write_tool")]
            )
            is None
        )

    def test_claim_without_write_returns_reason(self) -> None:
        reason = check_deliverable_write_claim("Saved to `out/report.md`", [])
        assert reason is not None
        assert "no successful file_write_tool" in reason
