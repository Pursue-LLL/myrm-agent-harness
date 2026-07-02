"""Unit tests for CompletionGuard middleware."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

import myrm_agent_harness.agent.middlewares.completion_guard as _cg_mod
from myrm_agent_harness.agent.middlewares.completion_guard import (
    COMPLETION_CHECK_TOOL_NAME,
    CompletionGuard,
    _build_checklist,
    classify_verification,
    reset_completion_guard,
)
from myrm_agent_harness.agent.security.guards.loop_guard_types import (
    CallRecord,
    SuccessLevel,
    VerificationCategory,
)

LOOP_GUARD_PATCH = "myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_loop_guard"


def _make_state(messages: list[object]) -> dict[str, object]:
    return {"messages": messages}


class TestCompletionGuardTriggerConditions:
    """Test trigger conditions for CompletionGuard.aafter_model.

    After removing one-shot WARNING, only CRITICAL blocking remains:
    the guard triggers only when code files were modified without verification.
    """

    def setup_method(self) -> None:
        self.guard = CompletionGuard()
        reset_completion_guard()

    @pytest.mark.asyncio
    async def test_skips_when_ai_has_tool_calls(self) -> None:
        """Should skip when AIMessage HAS tool_calls (except finish tools)."""
        state = _make_state(
            [
                AIMessage(content="", tool_calls=[{"id": "tc1", "name": "file_read_tool", "args": {}}]),
            ]
        )
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_triggers_when_ai_calls_finish_tool_with_unverified_writes(self) -> None:
        """Should trigger when AIMessage calls finish tool after modifying code without verification."""
        state = _make_state(
            [
                AIMessage(
                    content="",
                    tool_calls=[{
                        "id": "tc_answer",
                        "name": "request_answer_user_tool",
                        "args": {"reason": "Task complete"}
                    }]
                ),
            ]
        )

        code_write_record = CallRecord(
            tool_name="file_write_tool",
            args_hash="hash_code_write",
            args={"path": "/src/main.py"},
            success_level=SuccessLevel.FULL_SUCCESS,
        )

        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = [code_write_record]
            result = await self.guard.aafter_model(state, None)

        assert result is not None
        assert COMPLETION_CHECK_TOOL_NAME in str(result)

    @pytest.mark.asyncio
    async def test_skips_when_no_critical_errors(self) -> None:
        """Should pass through when no critical errors (no unverified code writes)."""
        state = _make_state([AIMessage(content="All done.")])
        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = []
            result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_skips_when_only_non_code_writes(self) -> None:
        """Should pass through when only non-code files were modified."""
        state = _make_state([AIMessage(content="Updated docs.")])
        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = [
                CallRecord(
                    tool_name="file_write_tool",
                    args_hash="abc",
                    args={"path": "/tmp/README.md"},
                    success_level=SuccessLevel.FULL_SUCCESS,
                )
            ]
            result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self) -> None:
        """Should skip when enabled=False."""
        guard = CompletionGuard(enabled=False)
        state = _make_state([AIMessage(content="Done.")])
        result = await guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_blocks_on_critical_errors(self) -> None:
        """Should block and increment rejection count when critical errors exist."""
        state = _make_state([AIMessage(content="All done!")])
        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = [
                CallRecord(
                    tool_name="file_write_tool",
                    args_hash="abc",
                    args={"path": "/tmp/test.py"},
                    success_level=SuccessLevel.FULL_SUCCESS,
                )
            ]
            result = await self.guard.aafter_model(state, None)

        assert result is not None
        assert _cg_mod._rejection_count == 1
        assert result["messages"][0].tool_calls[0]["args"].get("force_fail") is not True

    @pytest.mark.asyncio
    async def test_max_rejections_graceful_degradation(self) -> None:
        """Should inject force_fail=True when max rejections are reached."""
        self.guard._max_rejections = 2
        _cg_mod._rejection_count = 2
        state = _make_state([AIMessage(content="All done!")])
        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = [
                CallRecord(
                    tool_name="file_write_tool",
                    args_hash="abc",
                    args={"path": "/tmp/test.py"},
                    success_level=SuccessLevel.FULL_SUCCESS,
                )
            ]
            result = await self.guard.aafter_model(state, None)

        assert result is not None
        assert _cg_mod._rejection_count == 0
        assert result["messages"][0].tool_calls[0]["args"].get("force_fail") is True



class TestCompletionGuardReset:
    """Test reset_completion_guard resets rejection counter."""

    def test_reset_clears_rejection_count(self) -> None:
        _cg_mod._rejection_count = 5
        reset_completion_guard()
        assert _cg_mod._rejection_count == 0


class TestBuildChecklist:
    """Test _build_checklist generates correct verification items."""

    def test_empty_records(self) -> None:
        checklist, _ = _build_checklist([])
        assert "Confirm the response fully addresses" in checklist

    def test_write_without_verification_warns(self) -> None:
        """WRITE tools without verification evidence triggers a warning."""
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="abc",
                args={"path": "/tmp/test.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]
        checklist, _ = _build_checklist(records)
        assert "file_write_tool" in checklist
        assert "NO verification" in checklist

    def test_write_non_code_file_warns(self) -> None:
        """WRITE tools for non-code files without verification produces warning, not critical error."""
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="abc",
                args={"path": "/tmp/README.md"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]
        checklist, has_critical = _build_checklist(records)
        assert not has_critical
        assert "If these are text/data files" in checklist

    def test_write_with_passing_verification(self) -> None:
        """WRITE tools with passing verification produces light checklist."""
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="abc",
                args={"path": "/tmp/test.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="def",
                args={"command": "pytest"},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.TEST,
            ),
        ]
        checklist, _ = _build_checklist(records)
        assert "file_write_tool" in checklist
        assert "verified via" in checklist
        assert "test" in checklist

    def test_write_with_failing_verification(self) -> None:
        """WRITE tools with failing verification highlights the failure."""
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="abc",
                args={"path": "/tmp/test.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="def",
                args={"command": "pytest"},
                success_level=SuccessLevel.FAILURE,
                verification_type=VerificationCategory.TEST,
            ),
        ]
        checklist, _ = _build_checklist(records)
        assert "Verification failed" in checklist
        assert "test" in checklist

    def test_execute_tools_produce_verification(self) -> None:
        records = [
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="def",
                args={"command": "ls"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]
        checklist, _ = _build_checklist(records)
        assert "bash_code_execute_tool" in checklist
        assert "Verify execution results" in checklist

    def test_execute_failures_noted_in_execute_section(self) -> None:
        """EXECUTE failures without writes are WARNING, not CRITICAL."""
        records = [
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="xyz",
                args={"command": "failing_cmd"},
                success_level=SuccessLevel.FAILURE,
            ),
        ]
        checklist, has_critical = _build_checklist(records)
        assert not has_critical
        assert "WARNING" in checklist
        assert "failures" in checklist
        assert "bash_code_execute_tool" in checklist
        assert "unresolved failure" not in checklist

    def test_non_execute_failures_warning_when_no_writes(self) -> None:
        """Non-EXECUTE failures are WARNING (not CRITICAL) when no file writes."""
        records = [
            CallRecord(
                tool_name="web_fetch_tool",
                args_hash="abc",
                args={"url": "http://example.com"},
                success_level=SuccessLevel.FAILURE,
            ),
        ]
        checklist, has_critical = _build_checklist(records)
        assert not has_critical
        assert "WARNING" in checklist
        assert "web_fetch_tool" in checklist

    def test_non_execute_failures_critical_when_writes_exist(self) -> None:
        """Non-EXECUTE failures are CRITICAL when file writes exist."""
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="w1",
                args={"path": "/src/app.py", "content": "x"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="web_fetch_tool",
                args_hash="abc",
                args={"url": "http://example.com"},
                success_level=SuccessLevel.FAILURE,
            ),
        ]
        checklist, has_critical = _build_checklist(records)
        assert has_critical
        assert "unresolved failure" in checklist
        assert "web_fetch_tool" in checklist

    def test_browser_tools_produce_verification(self) -> None:
        records = [
            CallRecord(
                tool_name="browser_navigate_tool",
                args_hash="nav1",
                args={"url": "http://localhost:3000"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="browser_interact_tool",
                args_hash="int1",
                args={"action": "click"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]
        checklist, _ = _build_checklist(records)
        assert "browser_interact_tool" in checklist
        assert "browser_navigate_tool" in checklist
        assert "Verify browser interactions" in checklist

    def test_read_only_tools_no_verification(self) -> None:
        records = [
            CallRecord(
                tool_name="file_read_tool",
                args_hash="ghi",
                args={"path": "/tmp/test.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="grep_tool", args_hash="jkl", args={"pattern": "foo"}, success_level=SuccessLevel.FULL_SUCCESS
            ),
        ]
        checklist, _ = _build_checklist(records)
        assert "Confirm the response fully addresses" in checklist

    def test_plan_uncompleted_steps_critical_with_writes(self, tmp_path: Path) -> None:
        """Uncompleted plan steps are CRITICAL when file writes exist."""
        plan_dir = tmp_path / "planner"
        plan_dir.mkdir()
        plan_dir.joinpath("plan.json").write_text(
            """{
  "goal": "Test goal",
  "reasoning": "Test",
  "steps": [
    {"step_id": "1", "description": "Test step", "expected_output": "Done", "status": "pending"}
  ]
}""",
            encoding="utf-8",
        )

        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="w1",
                args={"path": "/src/app.py", "content": "x"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]

        checklist, has_critical = _build_checklist(records, workspace_root=str(tmp_path))

        assert has_critical
        assert "CRITICAL" in checklist
        assert "uncompleted steps in your Goal Plan" in checklist

    def test_plan_uncompleted_steps_warning_without_writes(self, tmp_path: Path) -> None:
        """Uncompleted plan steps are WARNING when no file writes (query task)."""
        plan_dir = tmp_path / "planner"
        plan_dir.mkdir()
        plan_dir.joinpath("plan.json").write_text(
            """{
  "goal": "Test goal",
  "reasoning": "Test",
  "steps": [
    {"step_id": "1", "description": "Test step", "expected_output": "Done", "status": "pending"}
  ]
}""",
            encoding="utf-8",
        )

        checklist, has_critical = _build_checklist([], workspace_root=str(tmp_path))

        assert not has_critical
        assert "WARNING" in checklist
        assert "uncompleted steps in your Goal Plan" in checklist

    def test_checklist_incomplete_critical_with_writes(self, tmp_path: Path) -> None:
        """Incomplete execution checklist items are CRITICAL when file writes exist."""
        checklist_dir = tmp_path / ".myrm"
        checklist_dir.mkdir()
        checklist_dir.joinpath("execution_checklist.json").write_text(
            """{
  "version": 1,
  "items": [{"id": "a", "content": "Run tests", "status": "pending"}]
}""",
            encoding="utf-8",
        )

        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="w1",
                args={"path": "/src/app.py", "content": "x"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]

        checklist, has_critical = _build_checklist(records, workspace_root=str(tmp_path))

        assert has_critical
        assert "Execution checklist has incomplete items" in checklist
        assert "update_execution_checklist_tool" in checklist


class TestCompletionGuardGetTools:
    """Test CompletionGuard exposes internal tool via get_tools."""

    def test_returns_completion_check_tool(self) -> None:
        guard = CompletionGuard()
        tools = guard.get_tools()
        assert len(tools) == 1
        assert tools[0].name == COMPLETION_CHECK_TOOL_NAME


class TestCompletionCheckTool:
    """Test the _completion_check tool function."""

    def test_tool_returns_checklist(self) -> None:
        from collections import deque

        from myrm_agent_harness.agent.middlewares.completion_guard import _completion_check_tool

        mock_window: deque[CallRecord] = deque(
            [
                CallRecord(
                    tool_name="file_write_tool",
                    args_hash="abc",
                    args={"path": "/tmp/out.py"},
                    success_level=SuccessLevel.FULL_SUCCESS,
                ),
            ]
        )

        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = mock_window
            result = _completion_check_tool.invoke({})

        assert "file_write_tool" in result

    def test_force_fail(self) -> None:
        from myrm_agent_harness.agent.middlewares.completion_guard import _completion_check_tool
        result = _completion_check_tool.invoke({"force_fail": True})
        assert "CRITICAL SYSTEM DIRECTIVE" in result


class TestClassifyVerification:
    """Test classify_verification command detection."""

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("pytest tests/", VerificationCategory.TEST),
            ("python -m pytest -x", VerificationCategory.TEST),
            ("npm test", VerificationCategory.TEST),
            ("npm run test", VerificationCategory.TEST),
            ("cargo test", VerificationCategory.TEST),
            ("pnpm test", VerificationCategory.TEST),
            ("pnpm run test", VerificationCategory.TEST),
            ("deno test", VerificationCategory.TEST),
            ("ruff check src/", VerificationCategory.LINT),
            ("eslint .", VerificationCategory.LINT),
            ("golangci-lint run", VerificationCategory.LINT),
            ("mypy src/", VerificationCategory.TYPECHECK),
            ("npx tsc --noEmit", VerificationCategory.TYPECHECK),
            ("cargo build", VerificationCategory.BUILD),
            ("npm run build", VerificationCategory.BUILD),
            ("yarn build", VerificationCategory.BUILD),
            ("pnpm run build", VerificationCategory.BUILD),
            ("bun run build", VerificationCategory.BUILD),
        ],
    )
    def test_detects_verification_commands(self, command: str, expected: VerificationCategory) -> None:
        assert classify_verification({"command": command}) == expected

    @pytest.mark.parametrize(
        "command",
        [
            "ls -la",
            "pip install pytest",
            "cat test.py",
            "echo hello",
            "git status",
            "npm test-helper",
            "npm test-setup --env prod",
        ],
    )
    def test_rejects_non_verification_commands(self, command: str) -> None:
        assert classify_verification({"command": command}) is None

    def test_empty_command(self) -> None:
        assert classify_verification({"command": ""}) is None
        assert classify_verification({}) is None

    def test_chained_commands(self) -> None:
        """Detects verification in chained commands (&&, ;)."""
        assert classify_verification({"command": "cd src && pytest tests/"}) == VerificationCategory.TEST
        assert classify_verification({"command": "cd src; ruff check ."}) == VerificationCategory.LINT

    def test_exact_match_without_trailing_args(self) -> None:
        """Exact command matches (no args after pattern)."""
        assert classify_verification({"command": "pytest"}) == VerificationCategory.TEST
        assert classify_verification({"command": "npm test"}) == VerificationCategory.TEST
        assert classify_verification({"command": "tsc"}) == VerificationCategory.TYPECHECK

    def test_chained_exact_match(self) -> None:
        """Chained commands with exact match at end."""
        assert classify_verification({"command": "cd dir && pytest"}) == VerificationCategory.TEST
        assert classify_verification({"command": "source .venv/bin/activate && mypy"}) == VerificationCategory.TYPECHECK


class TestFrontendBrowserVerificationWarning:
    """Test frontend rendering file detection triggers browser verification warning."""

    def test_frontend_tsx_without_browser_warns(self) -> None:
        """Modified .tsx file + no browser usage = WARNING in checklist."""
        records = [
            CallRecord(
                tool_name="file_edit_tool",
                args_hash="abc",
                args={"path": "/app/components/GoalCard.tsx"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="def",
                args={"command": "bun test"},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.TEST,
            ),
        ]
        checklist, has_critical = _build_checklist(records)
        assert not has_critical
        assert "Frontend rendering files were modified" in checklist
        assert "browser" in checklist.lower()

    def test_frontend_css_without_browser_warns(self) -> None:
        """Modified .css file + no browser usage = WARNING."""
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="abc",
                args={"path": "/app/styles/globals.css"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]
        checklist, _ = _build_checklist(records)
        assert "Frontend rendering files were modified" in checklist

    def test_frontend_with_browser_no_warning(self) -> None:
        """Modified .tsx + browser tools used = NO frontend warning."""
        records = [
            CallRecord(
                tool_name="file_edit_tool",
                args_hash="abc",
                args={"path": "/app/components/Header.tsx"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="browser_snapshot_tool",
                args_hash="snap1",
                args={},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]
        checklist, _ = _build_checklist(records)
        assert "Frontend rendering files were modified" not in checklist
        assert "Verify browser interactions" in checklist

    def test_test_tsx_no_warning(self) -> None:
        """Modified .test.tsx file should NOT trigger warning (non-render)."""
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="abc",
                args={"path": "/app/__tests__/GoalCard.test.tsx"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="def",
                args={"command": "vitest"},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.TEST,
            ),
        ]
        checklist, _ = _build_checklist(records)
        assert "Frontend rendering files were modified" not in checklist

    def test_store_tsx_no_warning(self) -> None:
        """Modified store .ts file should NOT trigger warning."""
        records = [
            CallRecord(
                tool_name="file_edit_tool",
                args_hash="abc",
                args={"path": "/app/store/usePlanStore.ts"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="def",
                args={"command": "bun test"},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.TEST,
            ),
        ]
        checklist, _ = _build_checklist(records)
        assert "Frontend rendering files were modified" not in checklist

    def test_config_file_no_warning(self) -> None:
        """Modified .config.ts should NOT trigger warning."""
        records = [
            CallRecord(
                tool_name="file_edit_tool",
                args_hash="abc",
                args={"path": "/app/tailwind.config.ts"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]
        checklist, _ = _build_checklist(records)
        assert "Frontend rendering files were modified" not in checklist

    def test_scss_without_browser_warns(self) -> None:
        """Modified .scss file + no browser usage = WARNING."""
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="abc",
                args={"path": "/app/styles/components/card.scss"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="def",
                args={"command": "npm run build"},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.BUILD,
            ),
        ]
        checklist, _ = _build_checklist(records)
        assert "Frontend rendering files were modified" in checklist

    def test_util_tsx_no_warning(self) -> None:
        """Modified util .tsx should NOT trigger warning."""
        records = [
            CallRecord(
                tool_name="file_edit_tool",
                args_hash="abc",
                args={"path": "/app/utils/formatDate.tsx"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="def",
                args={"command": "bun test"},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.TEST,
            ),
        ]
        checklist, _ = _build_checklist(records)
        assert "Frontend rendering files were modified" not in checklist

    def test_type_selector_tsx_triggers_warning(self) -> None:
        """TypeSelector.tsx should trigger warning (path segment match, not substring)."""
        records = [
            CallRecord(
                tool_name="file_edit_tool",
                args_hash="abc",
                args={"path": "/app/components/TypeSelector.tsx"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="def",
                args={"command": "bun test"},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.TEST,
            ),
        ]
        checklist, _ = _build_checklist(records)
        assert "Frontend rendering files were modified" in checklist

    def test_types_folder_tsx_no_warning(self) -> None:
        """File in types/ folder should NOT trigger warning."""
        records = [
            CallRecord(
                tool_name="file_edit_tool",
                args_hash="abc",
                args={"path": "/app/types/Button.tsx"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="def",
                args={"command": "bun test"},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.TEST,
            ),
        ]
        checklist, _ = _build_checklist(records)
        assert "Frontend rendering files were modified" not in checklist

    def test_astro_file_triggers_warning(self) -> None:
        """Modified .astro file should trigger warning."""
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="abc",
                args={"path": "/app/pages/index.astro"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]
        checklist, _ = _build_checklist(records)
        assert "Frontend rendering files were modified" in checklist

    def test_stories_file_no_warning(self) -> None:
        """Storybook .stories.tsx should NOT trigger warning."""
        records = [
            CallRecord(
                tool_name="file_edit_tool",
                args_hash="abc",
                args={"path": "/app/components/Button.stories.tsx"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="def",
                args={"command": "bun test"},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.TEST,
            ),
        ]
        checklist, _ = _build_checklist(records)
        assert "Frontend rendering files were modified" not in checklist

    def test_execute_failure_critical_when_writes_exist(self) -> None:
        """EXECUTE failures are CRITICAL when file writes exist."""
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="w1",
                args={"path": "/src/main.py", "content": "x"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="e1",
                args={"command": "pytest"},
                success_level=SuccessLevel.FAILURE,
            ),
        ]
        checklist, has_critical = _build_checklist(records)
        assert has_critical
        assert "CRITICAL" in checklist

    def test_execute_failure_warning_when_no_writes(self) -> None:
        """EXECUTE failures are only WARNING when no file writes (query task)."""
        records = [
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="e1",
                args={"command": "curl https://api.example.com"},
                success_level=SuccessLevel.FAILURE,
            ),
        ]
        checklist, has_critical = _build_checklist(records)
        assert not has_critical
        assert "WARNING" in checklist
        assert "CRITICAL" not in checklist

    def test_internal_tool_records_filtered(self) -> None:
        """CallRecords from internal tools (starting with _) are excluded."""
        records = [
            CallRecord(
                tool_name="_completion_check",
                args_hash="ic1",
                args={"workspace_root": "/tmp"},
                success_level=SuccessLevel.FAILURE,
            ),
        ]
        checklist, has_critical = _build_checklist(records)
        assert not has_critical
        assert "_completion_check" not in checklist
        assert "Confirm the response fully addresses" in checklist


class TestMixedMessageGuard:
    """Test the Mixed Message Guard feature in CompletionGuard.

    This guard strips read-only tool_calls when the AIMessage already contains
    a substantive final response, avoiding unnecessary tool execution rounds.
    """

    def setup_method(self) -> None:
        self.guard = CompletionGuard()
        reset_completion_guard()

    def _long_answer(self) -> str:
        """Generate a >500 char content with markdown structure."""
        return (
            "# Analysis of Router Structure\n\n"
            "The router is organized into the following modules:\n\n"
            "- **api/users.py**: Handles user CRUD operations\n"
            "- **api/auth.py**: Authentication and session management\n"
            "- **api/projects.py**: Project lifecycle management\n\n"
            "## Key Observations\n\n"
            "1. All routes follow RESTful conventions\n"
            "2. Authentication middleware is applied globally\n"
            "3. Rate limiting is configured per-endpoint\n\n"
            "```python\n"
            "router = APIRouter(prefix='/api/v1')\n"
            "```\n\n"
            "The architecture follows a clean separation of concerns "
            "with dependency injection for database sessions and proper "
            "error handling at each layer boundary."
        )

    @pytest.mark.asyncio
    async def test_strips_readonly_tools_with_substantive_content(self) -> None:
        """Core case: content is final answer + read-only tools -> strip."""
        state = _make_state([
            AIMessage(
                content=self._long_answer(),
                tool_calls=[
                    {"id": "tc1", "name": "file_read_tool", "args": {"path": "/src/router.py"}},
                    {"id": "tc2", "name": "grep_tool", "args": {"pattern": "route"}},
                ],
            ),
        ])
        result = await self.guard.aafter_model(state, None)

        assert result is not None
        ai_msg = result["messages"][0]
        assert isinstance(ai_msg, AIMessage)
        assert ai_msg.tool_calls == []
        assert "Analysis of Router Structure" in ai_msg.content

    @pytest.mark.asyncio
    async def test_preserves_mutation_tools(self) -> None:
        """Safety: content + mutation tool (write_file) -> do NOT strip."""
        state = _make_state([
            AIMessage(
                content=self._long_answer(),
                tool_calls=[
                    {"id": "tc1", "name": "write_file", "args": {"path": "/out.py", "content": "x"}},
                ],
            ),
        ])
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_preserves_mixed_mutation_and_readonly(self) -> None:
        """Safety: content + mix of mutation and read-only tools -> do NOT strip."""
        state = _make_state([
            AIMessage(
                content=self._long_answer(),
                tool_calls=[
                    {"id": "tc1", "name": "file_read_tool", "args": {"path": "/src/router.py"}},
                    {"id": "tc2", "name": "execute_command", "args": {"command": "echo hi"}},
                ],
            ),
        ])
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_short_content_not_stripped(self) -> None:
        """Content < 500 chars is likely in-progress narration -> do NOT strip."""
        state = _make_state([
            AIMessage(
                content="Let me check the file for you.",
                tool_calls=[
                    {"id": "tc1", "name": "file_read_tool", "args": {"path": "/src/router.py"}},
                ],
            ),
        ])
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_unfinished_content_not_stripped(self) -> None:
        """Content with 'unfinished' trailing marker -> do NOT strip."""
        content = self._long_answer() + "\n\nI'll now check the tests..."
        state = _make_state([
            AIMessage(
                content=content,
                tool_calls=[
                    {"id": "tc1", "name": "file_read_tool", "args": {"path": "/tests/"}},
                ],
            ),
        ])
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_structure_not_stripped(self) -> None:
        """Long content without markdown structure -> do NOT strip."""
        content = "x " * 300  # >500 chars but no markdown structure
        state = _make_state([
            AIMessage(
                content=content,
                tool_calls=[
                    {"id": "tc1", "name": "file_read_tool", "args": {"path": "/file"}},
                ],
            ),
        ])
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_finish_tools_bypass_mixed_guard(self) -> None:
        """When tool_calls include finish tool, take completion path not mixed guard."""
        state = _make_state([
            AIMessage(
                content=self._long_answer(),
                tool_calls=[
                    {"id": "tc1", "name": "request_answer_user_tool", "args": {"reason": "done"}},
                ],
            ),
        ])
        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = [
                CallRecord(
                    tool_name="file_write_tool",
                    args_hash="abc",
                    args={"path": "/src/app.py"},
                    success_level=SuccessLevel.FULL_SUCCESS,
                )
            ]
            result = await self.guard.aafter_model(state, None)

        assert result is not None
        assert result["messages"][0].tool_calls[0]["name"] == COMPLETION_CHECK_TOOL_NAME

    @pytest.mark.asyncio
    async def test_bash_tool_is_mutation(self) -> None:
        """bash_tool is classified as mutation -> do NOT strip."""
        state = _make_state([
            AIMessage(
                content=self._long_answer(),
                tool_calls=[
                    {"id": "tc1", "name": "bash_code_execute_tool", "args": {"command": "ls"}},
                ],
            ),
        ])
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_bash_code_execute_tool_is_mutation(self) -> None:
        """bash_code_execute_tool is classified as mutation -> do NOT strip."""
        state = _make_state([
            AIMessage(
                content=self._long_answer(),
                tool_calls=[
                    {"id": "tc1", "name": "bash_code_execute_tool", "args": {"command": "pytest"}},
                ],
            ),
        ])
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_content_no_trigger(self) -> None:
        """AIMessage with tool_calls but empty content -> do NOT trigger mixed guard."""
        state = _make_state([
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "tc1", "name": "file_read_tool", "args": {"path": "/file"}},
                ],
            ),
        ])
        result = await self.guard.aafter_model(state, None)
        assert result is None
