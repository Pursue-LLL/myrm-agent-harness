"""Tests for _assemble_execution_summary in stream_recovery_continuation.

Covers edge cases: empty window, duplicate files, various ToolGroup categories,
verification with different SuccessLevel values, and empty path handling.
"""

from collections import deque
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.agent.goals.types import (
    Goal,
    GoalBudget,
    GoalExecutionSummary,
    GoalStatus,
)
from myrm_agent_harness.agent.security.guards.loop_guard_types import (
    CallRecord,
    SuccessLevel,
    VerificationCategory,
)


def _make_goal(
    tokens_used: int = 5000,
    cost_usd: float = 0.05,
    time_used_seconds: int = 120,
    turns_used: int = 4,
) -> Goal:
    return Goal(
        goal_id="test-goal",
        session_id="test-session",
        objective="Test objective",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_tokens=50000),
        tokens_used=tokens_used,
        cost_usd=cost_usd,
        time_used_seconds=time_used_seconds,
        turns_used=turns_used,
    )


def _make_record(
    tool_name: str = "shell",
    args: dict | None = None,
    success_level: SuccessLevel | None = None,
    verification_type: VerificationCategory | None = None,
) -> CallRecord:
    return CallRecord(
        tool_name=tool_name,
        args_hash="hash123",
        args=args or {},
        success_level=success_level,
        verification_type=verification_type,
    )


def _get_mixin():
    """Create a minimal StreamContinuationRecoveryMixin instance."""
    from myrm_agent_harness.agent.streaming.stream_recovery_continuation import (
        StreamContinuationRecoveryMixin,
    )

    return StreamContinuationRecoveryMixin.__new__(StreamContinuationRecoveryMixin)


class TestAssembleExecutionSummary:
    """Tests for _assemble_execution_summary method."""

    @patch(
        "myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_loop_guard"
    )
    def test_empty_window(self, mock_get_guard: MagicMock):
        """Empty LoopGuard window produces summary with all-zero/empty fields."""
        guard = MagicMock()
        guard._window = deque()
        mock_get_guard.return_value = guard

        mixin = _get_mixin()
        goal = _make_goal()

        summary = mixin._assemble_execution_summary(goal)

        assert isinstance(summary, GoalExecutionSummary)
        assert summary.files_modified == ()
        assert summary.verifications == ()
        assert summary.browser_checks == 0
        assert summary.total_tokens == 5000
        assert summary.total_cost_usd == 0.05
        assert summary.execution_duration_s == 120.0
        assert summary.turns_used == 4

    @patch(
        "myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_loop_guard"
    )
    def test_write_records_deduplicate(self, mock_get_guard: MagicMock):
        """Duplicate file paths are deduplicated."""
        guard = MagicMock()
        guard._window = deque(
            [
                _make_record(tool_name="file_write_tool", args={"path": "/src/a.py"}),
                _make_record(tool_name="file_edit_tool", args={"path": "/src/b.py"}),
                _make_record(tool_name="file_write_tool", args={"path": "/src/a.py"}),
            ]
        )
        mock_get_guard.return_value = guard

        mixin = _get_mixin()
        goal = _make_goal()

        summary = mixin._assemble_execution_summary(goal)

        assert set(summary.files_modified) == {"/src/a.py", "/src/b.py"}
        assert len(summary.files_modified) == 2

    @patch(
        "myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_loop_guard"
    )
    def test_write_record_empty_path_ignored(self, mock_get_guard: MagicMock):
        """WRITE records with empty path are not included in files_modified."""
        guard = MagicMock()
        guard._window = deque(
            [
                _make_record(tool_name="file_write_tool", args={"path": ""}),
                _make_record(tool_name="file_write_tool", args={}),
                _make_record(tool_name="file_write_tool", args={"path": "/src/real.py"}),
            ]
        )
        mock_get_guard.return_value = guard

        mixin = _get_mixin()
        goal = _make_goal()

        summary = mixin._assemble_execution_summary(goal)

        assert summary.files_modified == ("/src/real.py",)

    @patch(
        "myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_loop_guard"
    )
    def test_browser_records_counted(self, mock_get_guard: MagicMock):
        """BROWSER group records increment browser_checks counter."""
        guard = MagicMock()
        guard._window = deque(
            [
                _make_record(tool_name="browser_navigate_tool", args={"url": "http://localhost:3000"}),
                _make_record(tool_name="browser_snapshot_tool", args={}),
                _make_record(tool_name="browser_interact_tool", args={"ref": "btn1"}),
            ]
        )
        mock_get_guard.return_value = guard

        mixin = _get_mixin()
        goal = _make_goal()

        summary = mixin._assemble_execution_summary(goal)

        assert summary.browser_checks == 3
        assert summary.files_modified == ()
        assert summary.verifications == ()

    @patch(
        "myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_loop_guard"
    )
    def test_verification_success_levels(self, mock_get_guard: MagicMock):
        """Verification records correctly map SuccessLevel to passed boolean."""
        guard = MagicMock()
        guard._window = deque(
            [
                _make_record(
                    tool_name="shell",
                    args={"command": "pytest"},
                    success_level=SuccessLevel.FULL_SUCCESS,
                    verification_type=VerificationCategory.TEST,
                ),
                _make_record(
                    tool_name="shell",
                    args={"command": "ruff check"},
                    success_level=SuccessLevel.FAILURE,
                    verification_type=VerificationCategory.LINT,
                ),
                _make_record(
                    tool_name="shell",
                    args={"command": "tsc"},
                    success_level=SuccessLevel.PARTIAL_SUCCESS,
                    verification_type=VerificationCategory.TYPECHECK,
                ),
                _make_record(
                    tool_name="shell",
                    args={"command": "cargo build"},
                    success_level=SuccessLevel.EMPTY_OK,
                    verification_type=VerificationCategory.BUILD,
                ),
            ]
        )
        mock_get_guard.return_value = guard

        mixin = _get_mixin()
        goal = _make_goal()

        summary = mixin._assemble_execution_summary(goal)

        assert len(summary.verifications) == 4
        assert summary.verifications[0] == {"cmd": "pytest", "passed": True}
        assert summary.verifications[1] == {"cmd": "ruff check", "passed": False}
        assert summary.verifications[2] == {"cmd": "tsc", "passed": True}
        assert summary.verifications[3] == {"cmd": "cargo build", "passed": True}

    @patch(
        "myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_loop_guard"
    )
    def test_verification_none_success_level(self, mock_get_guard: MagicMock):
        """Verification with None success_level is marked as not passed."""
        guard = MagicMock()
        guard._window = deque(
            [
                _make_record(
                    tool_name="shell",
                    args={"command": "npm test"},
                    success_level=None,
                    verification_type=VerificationCategory.TEST,
                ),
            ]
        )
        mock_get_guard.return_value = guard

        mixin = _get_mixin()
        goal = _make_goal()

        summary = mixin._assemble_execution_summary(goal)

        assert len(summary.verifications) == 1
        assert summary.verifications[0] == {"cmd": "npm test", "passed": False}

    @patch(
        "myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_loop_guard"
    )
    def test_mixed_records(self, mock_get_guard: MagicMock):
        """Mixed record types are correctly categorized."""
        guard = MagicMock()
        guard._window = deque(
            [
                _make_record(tool_name="file_write_tool", args={"path": "/app/main.py"}),
                _make_record(tool_name="browser_navigate_tool", args={"url": "http://localhost"}),
                _make_record(
                    tool_name="bash_code_execute_tool",
                    args={"command": "pytest -v"},
                    success_level=SuccessLevel.FULL_SUCCESS,
                    verification_type=VerificationCategory.TEST,
                ),
                _make_record(tool_name="file_read_tool", args={"path": "/app/main.py"}),
                _make_record(tool_name="file_edit_tool", args={"path": "/app/utils.py"}),
                _make_record(tool_name="browser_snapshot_tool", args={}),
            ]
        )
        mock_get_guard.return_value = guard

        mixin = _get_mixin()
        goal = _make_goal()

        summary = mixin._assemble_execution_summary(goal)

        assert summary.files_modified == ("/app/main.py", "/app/utils.py")
        assert summary.browser_checks == 2
        assert len(summary.verifications) == 1
        assert summary.verifications[0]["passed"] is True

    @patch(
        "myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_loop_guard"
    )
    def test_goal_accounting_fields(self, mock_get_guard: MagicMock):
        """Goal accounting data (tokens, cost, duration, turns) is correctly mapped."""
        guard = MagicMock()
        guard._window = deque()
        mock_get_guard.return_value = guard

        mixin = _get_mixin()
        goal = _make_goal(
            tokens_used=123456,
            cost_usd=1.23,
            time_used_seconds=7200,
            turns_used=15,
        )

        summary = mixin._assemble_execution_summary(goal)

        assert summary.total_tokens == 123456
        assert summary.total_cost_usd == 1.23
        assert summary.execution_duration_s == 7200.0
        assert summary.turns_used == 15

    @patch(
        "myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_loop_guard"
    )
    def test_files_sorted_alphabetically(self, mock_get_guard: MagicMock):
        """files_modified tuple is sorted alphabetically."""
        guard = MagicMock()
        guard._window = deque(
            [
                _make_record(tool_name="file_write_tool", args={"path": "/z/last.py"}),
                _make_record(tool_name="file_write_tool", args={"path": "/a/first.py"}),
                _make_record(tool_name="file_write_tool", args={"path": "/m/middle.py"}),
            ]
        )
        mock_get_guard.return_value = guard

        mixin = _get_mixin()
        goal = _make_goal()

        summary = mixin._assemble_execution_summary(goal)

        assert summary.files_modified == ("/a/first.py", "/m/middle.py", "/z/last.py")

    @patch(
        "myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_loop_guard"
    )
    def test_verification_uses_command_or_tool_name(self, mock_get_guard: MagicMock):
        """Verification cmd falls back to tool_name when command arg missing."""
        guard = MagicMock()
        guard._window = deque(
            [
                _make_record(
                    tool_name="custom_verify_tool",
                    args={},
                    success_level=SuccessLevel.FULL_SUCCESS,
                    verification_type=VerificationCategory.TEST,
                ),
                _make_record(
                    tool_name="shell",
                    args={"command": "make test"},
                    success_level=SuccessLevel.FULL_SUCCESS,
                    verification_type=VerificationCategory.TEST,
                ),
            ]
        )
        mock_get_guard.return_value = guard

        mixin = _get_mixin()
        goal = _make_goal()

        summary = mixin._assemble_execution_summary(goal)

        assert summary.verifications[0]["cmd"] == "custom_verify_tool"
        assert summary.verifications[1]["cmd"] == "make test"


class TestGoalExecutionSummaryEdgeCases:
    """Edge cases for GoalExecutionSummary dataclass."""

    def test_to_dict_converts_tuples_to_lists(self):
        """to_dict should convert tuples to lists for JSON serialization."""
        summary = GoalExecutionSummary(
            files_modified=("a.py", "b.py"),
            verifications=({"cmd": "pytest", "passed": True},),
            browser_checks=1,
            total_tokens=1000,
            total_cost_usd=0.01,
            execution_duration_s=10.0,
            turns_used=2,
        )
        d = summary.to_dict()

        assert isinstance(d["files_modified"], list)
        assert isinstance(d["verifications"], list)

    def test_zero_cost_goal(self):
        """GoalExecutionSummary handles zero-cost goals (e.g., cached responses)."""
        summary = GoalExecutionSummary(
            files_modified=(),
            verifications=(),
            browser_checks=0,
            total_tokens=0,
            total_cost_usd=0.0,
            execution_duration_s=0.0,
            turns_used=0,
        )
        d = summary.to_dict()

        assert d["total_tokens"] == 0
        assert d["total_cost_usd"] == 0.0
        assert d["execution_duration_s"] == 0.0

    def test_large_values(self):
        """GoalExecutionSummary handles large values (long-running goals)."""
        summary = GoalExecutionSummary(
            files_modified=tuple(f"file_{i}.py" for i in range(100)),
            verifications=tuple({"cmd": f"test_{i}", "passed": True} for i in range(50)),
            browser_checks=200,
            total_tokens=9_000_000,
            total_cost_usd=45.67,
            execution_duration_s=86400.0,
            turns_used=500,
        )
        d = summary.to_dict()

        assert len(d["files_modified"]) == 100
        assert len(d["verifications"]) == 50
        assert d["browser_checks"] == 200
        assert d["total_tokens"] == 9_000_000

    @pytest.mark.parametrize(
        "field",
        ["files_modified", "verifications", "browser_checks", "total_tokens", "total_cost_usd", "execution_duration_s", "turns_used"],
    )
    def test_all_fields_present_in_to_dict(self, field: str):
        """All fields are present in to_dict output."""
        summary = GoalExecutionSummary(
            files_modified=(),
            verifications=(),
            browser_checks=0,
            total_tokens=0,
            total_cost_usd=0.0,
            execution_duration_s=0.0,
            turns_used=0,
        )
        assert field in summary.to_dict()
