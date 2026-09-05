"""Unit tests for CompletionGuard middleware."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import myrm_agent_harness.agent.middlewares.completion.completion_guard as _cg_mod
from myrm_agent_harness.agent.middlewares.completion.completion_guard import (
    COMPLETION_CHECK_TOOL_NAME,
    CompletionGuard,
    classify_verification,
    reset_completion_guard,
)
from myrm_agent_harness.agent.middlewares.completion.completion_guard_checklist import (
    build_checklist,
    find_last_successful_verification_command,
)
from myrm_agent_harness.agent.security.guards.loop_guard import (
    CallRecord,
    SuccessLevel,
    VerificationCategory,
)
from myrm_agent_harness.core.security.tool_registry import (
    SafetyMetadata,
    register_ptc_safety_metadata,
)

LOOP_GUARD_PATCH = "myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware.get_loop_guard"


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
                AIMessage(
                    content="",
                    tool_calls=[{"id": "tc1", "name": "file_read_tool", "args": {}}],
                ),
            ]
        )
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_triggers_when_ai_calls_finish_tool_with_unverified_writes(
        self,
    ) -> None:
        """Should trigger when AIMessage calls finish tool after modifying code without verification."""
        state = _make_state(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "tc_answer",
                            "name": "request_answer_user_tool",
                            "args": {"reason": "Task complete"},
                        }
                    ],
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
    async def test_blocks_when_external_evidence_required_but_missing(self) -> None:
        """Freshness query without evidence tools should be blocked before finish."""
        state = _make_state(
            [
                HumanMessage(content="今天最新的 AI 新闻是什么？"),
                AIMessage(content="All done."),
            ]
        )
        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = []
            result = await self.guard.aafter_model(state, None)

        assert result is not None
        tool_calls = result["messages"][0].tool_calls
        assert tool_calls[0]["name"] == COMPLETION_CHECK_TOOL_NAME
        assert "evidence_reason" in tool_calls[0]["args"]

    @pytest.mark.asyncio
    async def test_allows_when_external_evidence_exists(self) -> None:
        """Freshness query with successful web evidence should pass through."""
        state = _make_state(
            [
                HumanMessage(content="Please give today's latest AI news summary."),
                AIMessage(content="All done."),
            ]
        )
        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = [
                CallRecord(
                    tool_name="web_search_tool",
                    args_hash="evidence1",
                    args={"query": "latest ai news"},
                    success_level=SuccessLevel.FULL_SUCCESS,
                )
            ]
            result = await self.guard.aafter_model(state, None)

        assert result is None

    @pytest.mark.asyncio
    async def test_blocks_when_unwritten_deliverable_detected_without_write(self) -> None:
        """Substantial code deliverable without write calls should be blocked."""
        code_body = (
            "```python\n"
            "# filename: src/server.py\n"
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            "\n"
            "@app.get('/health')\n"
            "def health():\n"
            "    return {'status': 'healthy'}\n"
            "```"
        )
        state = _make_state(
            [
                HumanMessage(content="请帮我写一个 FastAPI 服务代码"),
                AIMessage(content=f"这是实现的服务：\n{code_body}"),
            ]
        )
        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = []
            result = await self.guard.aafter_model(state, None)

        assert result is not None
        tool_calls = result["messages"][0].tool_calls
        assert tool_calls[0]["name"] == COMPLETION_CHECK_TOOL_NAME
        assert "deliverable_write_reason" in tool_calls[0]["args"]
        assert "Substantial unpersisted deliverables" in tool_calls[0]["args"]["deliverable_write_reason"]

    @pytest.mark.asyncio
    async def test_unwritten_deliverable_auto_staged_at_max_rejections(self) -> None:
        """At max rejections, unwritten deliverables should be auto-staged to workspace."""
        import tempfile

        code_body = (
            "```python\n"
            "# filename: draft_worker.py\n"
            "import time\n"
            "\n"
            "def run_worker():\n"
            "    print('working')\n"
            "    time.sleep(1)\n"
            "```"
        )
        state = _make_state(
            [
                HumanMessage(content="写一个 worker 脚本"),
                AIMessage(content=f"完成：\n{code_body}"),
            ]
        )
        guard = CompletionGuard(max_rejections=1)
        reset_completion_guard()

        with tempfile.TemporaryDirectory() as tmp_dir:
            runtime = {"configurable": {"context": {"workspace_root": tmp_dir}}}
            with patch(LOOP_GUARD_PATCH) as mock_guard:
                mock_guard.return_value._window = []
                # First rejection (rejection_count=1)
                r1 = await guard.aafter_model(state, runtime)
                assert r1 is not None

                # Second attempt hits max_rejections -> forced finish with auto-staging
                r2 = await guard.aafter_model(state, runtime)
                assert r2 is not None
                tool_calls = r2["messages"][0].tool_calls
                assert tool_calls[0]["args"]["force_fail"] is True
                assert "staged_artifacts" in tool_calls[0]["args"]
                staged = tool_calls[0]["args"]["staged_artifacts"]
                assert len(staged) == 1
                assert staged[0]["original_hint"] == "draft_worker.py"

                # Check physical file staged in workspace
                staged_path = Path(tmp_dir) / staged[0]["relative_path"]
                assert staged_path.exists()
                assert "run_worker" in staged_path.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_blocks_when_long_code_lines_without_write(self) -> None:
        """Substantial code deliverable without write calls should be blocked."""
        code_lines = "\n".join(f"line_{i} = {i} * 2" for i in range(40))
        msg_content = f"Here is the complete implementation:\n```python\n# filename: app.py\n{code_lines}\n```"
        state = _make_state(
            [
                HumanMessage(content="请帮我写一个完整的数据处理程序并保存"),
                AIMessage(content=msg_content),
            ]
        )
        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = []
            result = await self.guard.aafter_model(state, None)

        assert result is not None
        tool_calls = result["messages"][0].tool_calls
        assert tool_calls[0]["name"] == COMPLETION_CHECK_TOOL_NAME
        assert "deliverable_write_reason" in tool_calls[0]["args"]
        assert "Substantial unpersisted deliverables detected" in str(tool_calls[0]["args"]["deliverable_write_reason"])

    @pytest.mark.asyncio
    async def test_allows_when_mcp_ptc_bash_evidence_exists(self) -> None:
        """Freshness query with successful MCP PTC bash should pass through."""
        state = _make_state(
            [
                HumanMessage(content="Please give today's latest AI news summary."),
                AIMessage(content="All done."),
            ]
        )
        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = [
                CallRecord(
                    tool_name="bash_code_execute_tool",
                    args_hash="mcpbash1",
                    args={"command": "from skills.mcp_news_skill import fetch_latest"},
                    success_level=SuccessLevel.FULL_SUCCESS,
                )
            ]
            result = await self.guard.aafter_model(state, None)

        assert result is None

    @pytest.mark.asyncio
    async def test_does_not_block_plain_programming_question(self) -> None:
        """Non-freshness coding questions should not trigger external evidence gate."""
        state = _make_state(
            [
                HumanMessage(content="How do I link two lists in Python?"),
                AIMessage(content="All done."),
            ]
        )
        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = []
            result = await self.guard.aafter_model(state, None)

        assert result is None

    @pytest.mark.asyncio
    async def test_does_not_block_keyword_substring_in_code_question(self) -> None:
        """Word substrings like 'priceList' should not trigger freshness gate."""
        state = _make_state(
            [
                HumanMessage(content="How do I model a priceList type in TypeScript?"),
                AIMessage(content="All done."),
            ]
        )
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
        assert _cg_mod._forced_finish is True
        assert result["messages"][0].tool_calls[0]["args"].get("force_fail") is True

    @pytest.mark.asyncio
    async def test_after_forced_finish_guard_releases(self) -> None:
        """After max-rejections force-finish, subsequent completions pass through."""
        self.guard._max_rejections = 2
        _cg_mod._rejection_count = 2
        state = _make_state(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "tc_answer",
                            "name": "request_answer_user_tool",
                            "args": {"reason": "Task complete"},
                        }
                    ],
                )
            ]
        )
        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = [
                CallRecord(
                    tool_name="file_write_tool",
                    args_hash="abc",
                    args={"path": "/tmp/a.py"},
                    success_level=SuccessLevel.FULL_SUCCESS,
                )
            ]
            first = await self.guard.aafter_model(state, None)
        assert first is not None and _cg_mod._forced_finish is True
        # Next completion attempt is released without further injections.
        released = await self.guard.aafter_model(state, None)
        assert released is None

    @pytest.mark.asyncio
    async def test_guard_injection_does_not_mutate_original_message(self) -> None:
        """aafter_model must deep-copy the last AI message instead of mutating the
        state reference. Mutating the reference duplicates the tool_call declaration
        (two AIMessages, one ToolMessage) which hard-fails strict providers with
        'insufficient tool messages following tool_calls message'."""
        state = _make_state(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "tc_answer",
                            "name": "request_answer_user_tool",
                            "args": {"reason": "Task complete"},
                        }
                    ],
                )
            ]
        )
        original_ai = state["messages"][0]
        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = [
                CallRecord(
                    tool_name="file_write_tool",
                    args_hash="abc",
                    args={"path": "/tmp/a.py"},
                    success_level=SuccessLevel.FULL_SUCCESS,
                )
            ]
            result = await self.guard.aafter_model(state, None)

        assert result is not None
        injected = result["messages"][0]
        assert injected is not original_ai
        assert injected.tool_calls[0]["name"] == COMPLETION_CHECK_TOOL_NAME
        assert original_ai.tool_calls[0]["name"] == "request_answer_user_tool"


class TestCompletionGuardReset:
    """Test reset_completion_guard resets rejection counter."""

    def test_reset_clears_rejection_count(self) -> None:
        _cg_mod._rejection_count = 5
        _cg_mod._forced_finish = True
        reset_completion_guard()
        assert _cg_mod._rejection_count == 0
        assert _cg_mod._forced_finish is False


class TestBuildChecklist:
    """Test build_checklist generates correct verification items."""

    def test_empty_records(self) -> None:
        checklist, _ = build_checklist([])
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
        checklist, _ = build_checklist(records)
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
        checklist, has_critical = build_checklist(records)
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
        checklist, _ = build_checklist(records)
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
        checklist, _ = build_checklist(records)
        assert "Verification failed" in checklist
        assert "test" in checklist

    def test_write_with_trivial_verification_is_critical(self) -> None:
        """All verifications EMPTY_OK (trivial test output) triggers CRITICAL."""
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
                args={"command": "pytest tests/"},
                success_level=SuccessLevel.EMPTY_OK,
                verification_type=VerificationCategory.TEST,
            ),
        ]
        checklist, has_critical = build_checklist(records)
        assert has_critical
        assert "no meaningful results" in checklist
        assert "MUST ensure tests actually run" in checklist

    def test_execute_tools_produce_verification(self) -> None:
        records = [
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="def",
                args={"command": "ls"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]
        checklist, _ = build_checklist(records)
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
        checklist, has_critical = build_checklist(records)
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
        checklist, has_critical = build_checklist(records)
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
        checklist, has_critical = build_checklist(records)
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
        checklist, _ = build_checklist(records)
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
                tool_name="grep_tool",
                args_hash="jkl",
                args={"pattern": "foo"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]
        checklist, _ = build_checklist(records)
        assert "Confirm the response fully addresses" in checklist

    def test_todo_uncompleted_critical_with_writes(self, tmp_path: Path) -> None:
        """Uncompleted todos are CRITICAL when file writes exist."""
        progress_dir = tmp_path / ".myrm" / "progress"
        progress_dir.mkdir(parents=True)
        progress_dir.joinpath("todos.json").write_text(
            """{
  "goal": "Test goal",
  "todos": [
    {"id": "1", "content": "Test step", "status": "pending"}
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

        checklist, has_critical = build_checklist(records, workspace_root=str(tmp_path))

        assert has_critical
        assert "CRITICAL" in checklist
        assert "incomplete todos" in checklist

    def test_todo_uncompleted_warning_without_writes(self, tmp_path: Path) -> None:
        """Uncompleted todos are WARNING when no file writes."""
        progress_dir = tmp_path / ".myrm" / "progress"
        progress_dir.mkdir(parents=True)
        progress_dir.joinpath("todos.json").write_text(
            """{
  "goal": "Test goal",
  "todos": [
    {"id": "1", "content": "Test step", "status": "pending"}
  ]
}""",
            encoding="utf-8",
        )

        checklist, has_critical = build_checklist([], workspace_root=str(tmp_path))

        assert not has_critical
        assert "WARNING" in checklist
        assert "incomplete todos" in checklist


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

        from myrm_agent_harness.agent.middlewares.completion.completion_guard import (
            _completion_check_tool,
        )

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
        from myrm_agent_harness.agent.middlewares.completion.completion_guard import (
            _completion_check_tool,
        )

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
    def test_detects_verification_commands(
        self, command: str, expected: VerificationCategory
    ) -> None:
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
        assert (
            classify_verification({"command": "cd src && pytest tests/"})
            == VerificationCategory.TEST
        )
        assert (
            classify_verification({"command": "cd src; ruff check ."})
            == VerificationCategory.LINT
        )

    def test_exact_match_without_trailing_args(self) -> None:
        """Exact command matches (no args after pattern)."""
        assert classify_verification({"command": "pytest"}) == VerificationCategory.TEST
        assert (
            classify_verification({"command": "npm test"}) == VerificationCategory.TEST
        )
        assert (
            classify_verification({"command": "tsc"}) == VerificationCategory.TYPECHECK
        )

    def test_chained_exact_match(self) -> None:
        """Chained commands with exact match at end."""
        assert (
            classify_verification({"command": "cd dir && pytest"})
            == VerificationCategory.TEST
        )
        assert (
            classify_verification({"command": "source .venv/bin/activate && mypy"})
            == VerificationCategory.TYPECHECK
        )


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
        checklist, has_critical = build_checklist(records)
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
        checklist, _ = build_checklist(records)
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
        checklist, _ = build_checklist(records)
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
        checklist, _ = build_checklist(records)
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
        checklist, _ = build_checklist(records)
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
        checklist, _ = build_checklist(records)
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
        checklist, _ = build_checklist(records)
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
        checklist, _ = build_checklist(records)
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
        checklist, _ = build_checklist(records)
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
        checklist, _ = build_checklist(records)
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
        checklist, _ = build_checklist(records)
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
        checklist, _ = build_checklist(records)
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
        checklist, has_critical = build_checklist(records)
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
        checklist, has_critical = build_checklist(records)
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
        checklist, has_critical = build_checklist(records)
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
        state = _make_state(
            [
                AIMessage(
                    content=self._long_answer(),
                    tool_calls=[
                        {
                            "id": "tc1",
                            "name": "file_read_tool",
                            "args": {"path": "/src/router.py"},
                        },
                        {
                            "id": "tc2",
                            "name": "grep_tool",
                            "args": {"pattern": "route"},
                        },
                    ],
                ),
            ]
        )
        result = await self.guard.aafter_model(state, None)

        assert result is not None
        ai_msg = result["messages"][0]
        assert isinstance(ai_msg, AIMessage)
        assert ai_msg.tool_calls == []
        assert "Analysis of Router Structure" in ai_msg.content

    @pytest.mark.asyncio
    async def test_preserves_mutation_tools(self) -> None:
        """Safety: content + mutation tool (write_file) -> do NOT strip."""
        state = _make_state(
            [
                AIMessage(
                    content=self._long_answer(),
                    tool_calls=[
                        {
                            "id": "tc1",
                            "name": "write_file",
                            "args": {"path": "/out.py", "content": "x"},
                        },
                    ],
                ),
            ]
        )
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_preserves_background_process_mutation(self) -> None:
        """Safety: content + bash_process_tool(kill) must NOT be stripped — the
        kill/stdin actions mutate process state and stripping would silently
        drop the cleanup side effect."""
        state = _make_state(
            [
                AIMessage(
                    content=self._long_answer(),
                    tool_calls=[
                        {
                            "id": "tc1",
                            "name": "bash_process_tool",
                            "args": {"action": "kill", "pid": 123, "force": False},
                        },
                    ],
                ),
            ]
        )
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tool_name", "args"),
        [
            ("ask_question_tool", {"question": "Which quarter?"}),
            ("render_ui_tool", {"component": "KanbanBoard"}),
            ("update_ui_data_tool", {"surface_id": "sb1", "data": {"done": 3}}),
            ("browser_ask_human_tool", {"reason": "Enter SMS code"}),
        ],
    )
    async def test_preserves_interaction_ui_carriers(
        self, tool_name: str, args: dict[str, object]
    ) -> None:
        """Safety: content + interaction/UI carrier must NOT be stripped — these
        are registry read-only but carry user-visible functionality (question,
        grant, render); dropping them breaks the interaction/UI chain."""
        state = _make_state(
            [
                AIMessage(
                    content=self._long_answer(),
                    tool_calls=[{"id": "tc1", "name": tool_name, "args": args}],
                ),
            ]
        )
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_preserves_skill_market_mutation(self) -> None:
        """Safety: content + skill_market_tool(install) must NOT be stripped —
        the install/uninstall actions write the skill library; registry marks it
        read-only but the actions are effectful, so stripping would silently
        drop the install."""
        state = _make_state(
            [
                AIMessage(
                    content=self._long_answer(),
                    tool_calls=[
                        {
                            "id": "tc1",
                            "name": "skill_market_tool",
                            "args": {
                                "action": "install",
                                "skill_id": "web-search",
                                "source": "market",
                            },
                        },
                    ],
                ),
            ]
        )
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_preserves_mixed_mutation_and_readonly(self) -> None:
        """Safety: content + mix of mutation and read-only tools -> do NOT strip."""
        state = _make_state(
            [
                AIMessage(
                    content=self._long_answer(),
                    tool_calls=[
                        {
                            "id": "tc1",
                            "name": "file_read_tool",
                            "args": {"path": "/src/router.py"},
                        },
                        {
                            "id": "tc2",
                            "name": "execute_command",
                            "args": {"command": "echo hi"},
                        },
                    ],
                ),
            ]
        )
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_short_content_not_stripped(self) -> None:
        """Content < 500 chars is likely in-progress narration -> do NOT strip."""
        state = _make_state(
            [
                AIMessage(
                    content="Let me check the file for you.",
                    tool_calls=[
                        {
                            "id": "tc1",
                            "name": "file_read_tool",
                            "args": {"path": "/src/router.py"},
                        },
                    ],
                ),
            ]
        )
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_unfinished_content_not_stripped(self) -> None:
        """Content with 'unfinished' trailing marker -> do NOT strip."""
        content = self._long_answer() + "\n\nI'll now check the tests..."
        state = _make_state(
            [
                AIMessage(
                    content=content,
                    tool_calls=[
                        {
                            "id": "tc1",
                            "name": "file_read_tool",
                            "args": {"path": "/tests/"},
                        },
                    ],
                ),
            ]
        )
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_structure_not_stripped(self) -> None:
        """Long content without markdown structure -> do NOT strip."""
        content = "x " * 300  # >500 chars but no markdown structure
        state = _make_state(
            [
                AIMessage(
                    content=content,
                    tool_calls=[
                        {
                            "id": "tc1",
                            "name": "file_read_tool",
                            "args": {"path": "/file"},
                        },
                    ],
                ),
            ]
        )
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_finish_tools_bypass_mixed_guard(self) -> None:
        """When tool_calls include finish tool, take completion path not mixed guard."""
        state = _make_state(
            [
                AIMessage(
                    content=self._long_answer(),
                    tool_calls=[
                        {
                            "id": "tc1",
                            "name": "request_answer_user_tool",
                            "args": {"reason": "done"},
                        },
                    ],
                ),
            ]
        )
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
        state = _make_state(
            [
                AIMessage(
                    content=self._long_answer(),
                    tool_calls=[
                        {
                            "id": "tc1",
                            "name": "bash_code_execute_tool",
                            "args": {"command": "ls"},
                        },
                    ],
                ),
            ]
        )
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_bash_code_execute_tool_is_mutation(self) -> None:
        """bash_code_execute_tool is classified as mutation -> do NOT strip."""
        state = _make_state(
            [
                AIMessage(
                    content=self._long_answer(),
                    tool_calls=[
                        {
                            "id": "tc1",
                            "name": "bash_code_execute_tool",
                            "args": {"command": "pytest"},
                        },
                    ],
                ),
            ]
        )
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_content_no_trigger(self) -> None:
        """AIMessage with tool_calls but empty content -> do NOT trigger mixed guard."""
        state = _make_state(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "tc1",
                            "name": "file_read_tool",
                            "args": {"path": "/file"},
                        },
                    ],
                ),
            ]
        )
        result = await self.guard.aafter_model(state, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_keeps_tool_calls_when_external_evidence_missing(self) -> None:
        """Freshness query + substantive content + read-only tools + NO evidence:
        must NOT strip — the agent needs to gather real data (anti-hallucination)."""
        state = _make_state(
            [
                HumanMessage(content="今天最新的 AI 新闻是什么？"),
                AIMessage(
                    content=self._long_answer(),
                    tool_calls=[
                        {
                            "id": "tc1",
                            "name": "web_search_tool",
                            "args": {"query": "AI news today"},
                        },
                    ],
                ),
            ]
        )
        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = []
            result = await self.guard.aafter_model(state, None)

        assert result is None

    @pytest.mark.asyncio
    async def test_strips_when_external_evidence_exists(self) -> None:
        """Freshness query + substantive content + read-only tools WITH evidence:
        still strips to save tokens."""
        state = _make_state(
            [
                HumanMessage(content="今天最新的 AI 新闻是什么？"),
                AIMessage(
                    content=self._long_answer(),
                    tool_calls=[
                        {
                            "id": "tc1",
                            "name": "web_search_tool",
                            "args": {"query": "AI news today"},
                        },
                    ],
                ),
            ]
        )
        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = [
                CallRecord(
                    tool_name="web_search_tool",
                    args_hash="evidence1",
                    args={"query": "AI news"},
                    success_level=SuccessLevel.FULL_SUCCESS,
                )
            ]
            result = await self.guard.aafter_model(state, None)

        assert result is not None
        ai_msg = result["messages"][0]
        assert ai_msg.tool_calls == []

    @pytest.mark.asyncio
    async def test_keeps_unannotated_mcp_tool_calls(self) -> None:
        """MCP tool without readOnlyHint (fail-closed non-read-only) must NOT be
        stripped — stripping could silently drop a side-effecting call such as
        booking/payment while the content claims completion."""
        state = _make_state(
            [
                HumanMessage(content="帮我订一张明天去北京的火车票"),
                AIMessage(
                    content=self._long_answer(),
                    tool_calls=[
                        {
                            "id": "tc1",
                            "name": "mcp__payments__charge_card",
                            "args": {"amount": 553},
                        },
                    ],
                ),
            ]
        )
        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = []
            result = await self.guard.aafter_model(state, None)

        assert result is None

    @pytest.mark.asyncio
    async def test_strips_readonly_annotated_mcp_tool_calls(self) -> None:
        """MCP tool with explicit readOnlyHint=True is safe to strip — keeps
        the token-saving optimization for genuinely read-only MCP servers."""
        tool_name = "mcp__meteo__get_temperature"
        register_ptc_safety_metadata(
            "mcp_meteo_skill",
            tool_name,
            SafetyMetadata(is_read_only=True, is_concurrent_safe=True),
            {"readOnlyHint": True},
        )
        state = _make_state(
            [
                HumanMessage(content="北京现在多少度？"),
                AIMessage(
                    content=self._long_answer(),
                    tool_calls=[
                        {
                            "id": "tc1",
                            "name": tool_name,
                            "args": {"city": "Beijing"},
                        },
                    ],
                ),
            ]
        )
        with patch(LOOP_GUARD_PATCH) as mock_guard:
            mock_guard.return_value._window = []
            result = await self.guard.aafter_model(state, None)

        assert result is not None
        ai_msg = result["messages"][0]
        assert ai_msg.tool_calls == []


class TestTemporalOrderChecking:
    """Test temporal ordering detection in build_checklist.

    Verifies that code writes AFTER the last successful verification
    are flagged as CRITICAL, forcing re-verification.
    """

    def test_code_write_after_verification_is_critical(self) -> None:
        """Write → verify → write again → CRITICAL (post-verification write)."""
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="w1",
                args={"path": "/src/app.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="v1",
                args={"command": "pytest tests/"},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.TEST,
            ),
            CallRecord(
                tool_name="file_edit_tool",
                args_hash="w2",
                args={"path": "/src/app.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]
        checklist, has_critical = build_checklist(records)
        assert has_critical
        assert "AFTER the last successful verification" in checklist

    def test_code_write_before_verification_not_critical(self) -> None:
        """Write → verify → no more writes → not critical."""
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="w1",
                args={"path": "/src/app.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="v1",
                args={"command": "pytest tests/"},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.TEST,
            ),
        ]
        checklist, has_critical = build_checklist(records)
        assert not has_critical
        assert "verified via" in checklist

    def test_non_code_write_after_verification_not_critical(self) -> None:
        """Write code → verify → write non-code → not critical."""
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="w1",
                args={"path": "/src/app.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="v1",
                args={"command": "pytest"},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.TEST,
            ),
            CallRecord(
                tool_name="file_write_tool",
                args_hash="w2",
                args={"path": "/docs/README.md"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]
        _checklist, has_critical = build_checklist(records)
        assert not has_critical

    def test_failed_verification_not_used_as_anchor(self) -> None:
        """Failed verifications are NOT treated as temporal anchors."""
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="w1",
                args={"path": "/src/app.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="v1",
                args={"command": "pytest"},
                success_level=SuccessLevel.FAILURE,
                verification_type=VerificationCategory.TEST,
            ),
        ]
        checklist, has_critical = build_checklist(records)
        assert has_critical
        assert "Verification failed" in checklist


class TestFindLastSuccessfulVerificationCommand:
    """Test find_last_successful_verification_command extraction."""

    def test_finds_last_successful_command(self) -> None:
        records = [
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="v1",
                args={"command": "pytest tests/ -x"},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.TEST,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="v2",
                args={"command": "ruff check src/"},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.LINT,
            ),
        ]
        cmd = find_last_successful_verification_command(records)
        assert cmd == "ruff check src/"

    def test_skips_failed_verifications(self) -> None:
        records = [
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="v1",
                args={"command": "pytest tests/"},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.TEST,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="v2",
                args={"command": "ruff check src/"},
                success_level=SuccessLevel.FAILURE,
                verification_type=VerificationCategory.LINT,
            ),
        ]
        cmd = find_last_successful_verification_command(records)
        assert cmd == "pytest tests/"

    def test_returns_none_when_no_verifications(self) -> None:
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="w1",
                args={"path": "/src/app.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]
        cmd = find_last_successful_verification_command(records)
        assert cmd is None

    def test_returns_none_for_empty_command(self) -> None:
        records = [
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="v1",
                args={"command": ""},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.TEST,
            ),
        ]
        cmd = find_last_successful_verification_command(records)
        assert cmd is None


class TestIndependentRerun:
    """Test CompletionGuard independent re-run in sandbox."""

    def setup_method(self) -> None:
        self.guard = CompletionGuard()
        reset_completion_guard()

    @pytest.mark.asyncio
    async def test_rerun_passes_allows_completion(self) -> None:
        """When independent re-run passes, agent is allowed to complete."""
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="w1",
                args={"path": "/src/app.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="v1",
                args={"command": "pytest tests/"},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.TEST,
            ),
            CallRecord(
                tool_name="file_edit_tool",
                args_hash="w2",
                args={"path": "/src/app.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]

        mock_executor = MagicMock()
        mock_result = MagicMock(exit_code=0, stdout="OK", stderr="")
        mock_executor.execute_bash = AsyncMock(return_value=mock_result)

        state = _make_state([AIMessage(content="Done.")])
        with (
            patch(LOOP_GUARD_PATCH) as mock_guard,
            patch(
                "myrm_agent_harness.toolkits.code_execution.executors.base.get_executor",
                return_value=mock_executor,
            ),
        ):
            mock_guard.return_value._window = records
            result = await self.guard.aafter_model(state, None)

        assert result is None

    @pytest.mark.asyncio
    async def test_rerun_fails_blocks_completion(self) -> None:
        """When independent re-run fails, agent is blocked from completing."""
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="w1",
                args={"path": "/src/app.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="v1",
                args={"command": "pytest tests/"},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.TEST,
            ),
            CallRecord(
                tool_name="file_edit_tool",
                args_hash="w2",
                args={"path": "/src/app.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]

        mock_executor = MagicMock()
        mock_result = MagicMock(exit_code=1, stdout="", stderr="FAILED")
        mock_executor.execute_bash = AsyncMock(return_value=mock_result)

        state = _make_state([AIMessage(content="Done.")])
        with (
            patch(LOOP_GUARD_PATCH) as mock_guard,
            patch(
                "myrm_agent_harness.toolkits.code_execution.executors.base.get_executor",
                return_value=mock_executor,
            ),
        ):
            mock_guard.return_value._window = records
            result = await self.guard.aafter_model(state, None)

        assert result is not None
        assert COMPLETION_CHECK_TOOL_NAME in str(result)

    @pytest.mark.asyncio
    async def test_failed_verification_not_bypassed_by_rerun(self) -> None:
        """When critical error is 'verification failed' (not temporal), rerun must NOT bypass."""
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="w1",
                args={"path": "/src/app.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="v1",
                args={"command": "pytest tests/"},
                success_level=SuccessLevel.FAILURE,
                verification_type=VerificationCategory.TEST,
            ),
        ]

        mock_executor = MagicMock()
        mock_result = MagicMock(exit_code=0, stdout="OK", stderr="")
        mock_executor.execute_bash = AsyncMock(return_value=mock_result)

        state = _make_state([AIMessage(content="Done.")])
        with (
            patch(LOOP_GUARD_PATCH) as mock_guard,
            patch(
                "myrm_agent_harness.toolkits.code_execution.executors.base.get_executor",
                return_value=mock_executor,
            ),
        ):
            mock_guard.return_value._window = records
            result = await self.guard.aafter_model(state, None)

        assert result is not None
        assert COMPLETION_CHECK_TOOL_NAME in str(result)

    @pytest.mark.asyncio
    async def test_no_executor_falls_back_to_blocking(self) -> None:
        """When sandbox executor is unavailable, falls back to blocking."""
        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="w1",
                args={"path": "/src/app.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
            CallRecord(
                tool_name="bash_code_execute_tool",
                args_hash="v1",
                args={"command": "pytest tests/"},
                success_level=SuccessLevel.FULL_SUCCESS,
                verification_type=VerificationCategory.TEST,
            ),
            CallRecord(
                tool_name="file_edit_tool",
                args_hash="w2",
                args={"path": "/src/app.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            ),
        ]

        state = _make_state([AIMessage(content="Done.")])
        with (
            patch(LOOP_GUARD_PATCH) as mock_guard,
            patch(
                "myrm_agent_harness.toolkits.code_execution.executors.base.get_executor",
                return_value=None,
            ),
        ):
            mock_guard.return_value._window = records
            result = await self.guard.aafter_model(state, None)

        assert result is not None
        assert COMPLETION_CHECK_TOOL_NAME in str(result)


class TestExtractLatestHumanText:
    """Tests for extract_latest_human_text covering multimodal content."""

    def test_string_content(self) -> None:
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            extract_latest_human_text,
        )

        messages = [HumanMessage(content="What is the latest news?")]
        assert extract_latest_human_text(messages) == "What is the latest news?"

    def test_strips_bound_skills_catalog(self) -> None:
        """System-injected <bound_skills> catalog must not leak into freshness detection."""
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            extract_latest_human_text,
        )

        messages = [
            HumanMessage(
                content=(
                    '<bound_skills hash="abc">\n<skills>\n<row><name>live search</name></row>\n'
                    "</skills>\n</bound_skills>\n\n只回复 OK"
                )
            )
        ]
        assert extract_latest_human_text(messages) == "只回复 OK"

    def test_strips_bound_skills_from_multimodal(self) -> None:
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            extract_latest_human_text,
        )

        messages = [
            HumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": (
                            '<bound_skills hash="abc">\n<skills>\n<row><name>live stats</name></row>\n'
                            "</skills>\n</bound_skills>\n\n只回复 OK"
                        ),
                    }
                ]
            )
        ]
        assert extract_latest_human_text(messages) == "只回复 OK"

    def test_multimodal_list_content(self) -> None:
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            extract_latest_human_text,
        )

        messages = [
            HumanMessage(
                content=[
                    {"type": "text", "text": "Describe this image"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "http://example.com/img.png"},
                    },
                ]
            )
        ]
        assert extract_latest_human_text(messages) == "Describe this image"

    def test_multimodal_list_multiple_text_parts(self) -> None:
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            extract_latest_human_text,
        )

        messages = [
            HumanMessage(
                content=[
                    {"type": "text", "text": "Hello"},
                    {"type": "text", "text": "world"},
                ]
            )
        ]
        assert extract_latest_human_text(messages) == "Hello world"

    def test_empty_string_content_skipped(self) -> None:
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            extract_latest_human_text,
        )

        messages = [
            HumanMessage(content="   "),
            HumanMessage(content="Actual question"),
        ]
        assert extract_latest_human_text(messages) == "Actual question"

    def test_empty_list_returns_none(self) -> None:
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            extract_latest_human_text,
        )

        assert extract_latest_human_text([]) is None

    def test_no_human_messages(self) -> None:
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            extract_latest_human_text,
        )

        messages = [AIMessage(content="I am AI")]
        assert extract_latest_human_text(messages) is None


class TestHasExternalEvidence:
    """Tests for has_external_evidence helper."""

    def test_returns_true_for_successful_evidence_tool(self) -> None:
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            has_external_evidence,
        )

        record = CallRecord(
            tool_name="web_search_tool",
            args_hash="s1",
            args={"query": "test"},
            success_level=SuccessLevel.FULL_SUCCESS,
        )
        assert has_external_evidence([record]) is True

    def test_returns_false_for_failed_evidence_tool(self) -> None:
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            has_external_evidence,
        )

        record = CallRecord(
            tool_name="web_search_tool",
            args_hash="s1",
            args={"query": "test"},
            success_level=SuccessLevel.FAILURE,
        )
        assert has_external_evidence([record]) is False

    def test_returns_false_for_non_evidence_tool(self) -> None:
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            has_external_evidence,
        )

        record = CallRecord(
            tool_name="file_read_tool",
            args_hash="r1",
            args={"path": "/tmp/x"},
            success_level=SuccessLevel.FULL_SUCCESS,
        )
        assert has_external_evidence([record]) is False

    def test_returns_false_for_empty_records(self) -> None:
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            has_external_evidence,
        )

        assert has_external_evidence([]) is False

    def test_returns_true_for_successful_mcp_ptc_bash(self) -> None:
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            has_external_evidence,
        )

        record = CallRecord(
            tool_name="bash_code_execute_tool",
            args_hash="mcp1",
            args={
                "command": (
                    'python3 -c "from skills.mcp_12306_skill import get_tickets; print(\\"ok\\")"'
                ),
            },
            success_level=SuccessLevel.FULL_SUCCESS,
        )
        assert has_external_evidence([record]) is True

    def test_returns_false_for_failed_mcp_ptc_bash(self) -> None:
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            has_external_evidence,
        )

        record = CallRecord(
            tool_name="bash_code_execute_tool",
            args_hash="mcp2",
            args={"command": "from skills.mcp_12306_skill import get_tickets"},
            success_level=SuccessLevel.FAILURE,
        )
        assert has_external_evidence([record]) is False

    def test_returns_false_for_plain_bash_without_mcp_marker(self) -> None:
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            has_external_evidence,
        )

        record = CallRecord(
            tool_name="bash_code_execute_tool",
            args_hash="bash1",
            args={"command": "pytest -q"},
            success_level=SuccessLevel.FULL_SUCCESS,
        )
        assert has_external_evidence([record]) is False

    def test_returns_false_when_bash_args_are_not_a_dict(self) -> None:
        """Bash args that are empty or lack command/code must not count as MCP PTC evidence."""
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            has_external_evidence,
        )

        empty_args = CallRecord(
            tool_name="bash_code_execute_tool",
            args_hash="b0",
            args={},
            success_level=SuccessLevel.FULL_SUCCESS,
        )
        assert has_external_evidence([empty_args]) is False

        non_command_args = CallRecord(
            tool_name="bash_code_execute_tool",
            args_hash="b1",
            args={"timeout": 120},
            success_level=SuccessLevel.FULL_SUCCESS,
        )
        assert has_external_evidence([non_command_args]) is False

    def test_requires_evidence_for_citation_and_web_hint_combination(self) -> None:
        """A request with citation+web hints but no freshness word still requires evidence."""
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            build_external_evidence_reason,
        )

        messages = [
            HumanMessage(content="Please summarize with sources from the web."),
            AIMessage(content="All done."),
        ]
        reason = build_external_evidence_reason(messages=messages, records=[])
        assert reason is not None
        assert "external/freshness need" in reason

    def test_no_evidence_required_without_freshness_or_citation_web_hint(self) -> None:
        """Plain questions must not require external evidence."""
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            build_external_evidence_reason,
        )

        messages = [
            HumanMessage(content="Explain how merge sort works."),
            AIMessage(content="Merge sort is a divide-and-conquer algorithm."),
        ]
        reason = build_external_evidence_reason(messages=messages, records=[])
        assert reason is None

    def test_citation_alone_without_web_hint_requires_no_evidence(self) -> None:
        """A citation keyword alone (no web hint) must not trigger the gate."""
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            build_external_evidence_reason,
        )

        messages = [
            HumanMessage(content="Which sources describe this algorithm?"),
            AIMessage(content="All done."),
        ]
        reason = build_external_evidence_reason(messages=messages, records=[])
        assert reason is None

    def test_no_evidence_required_for_internal_code_task_with_latest(self) -> None:
        """A local code task phrased with 'latest' must NOT require external
        evidence — the agent would otherwise be pushed into a meaningless web
        search for its own repository's recent changes."""
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            build_external_evidence_reason,
        )

        messages = [
            HumanMessage(content="帮我分析一下项目里最新改动的代码逻辑"),
            AIMessage(content="All done."),
        ]
        reason = build_external_evidence_reason(messages=messages, records=[])
        assert reason is None

    def test_internal_code_task_english_variant_no_evidence(self) -> None:
        """English equivalent of an internal code task is also exempted."""
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            build_external_evidence_reason,
        )

        messages = [
            HumanMessage(
                content="What are the latest code changes in the auth module?"
            ),
            AIMessage(content="All done."),
        ]
        reason = build_external_evidence_reason(messages=messages, records=[])
        assert reason is None

    def test_evidence_still_required_for_genuine_freshness(self) -> None:
        """A real freshness request without local-work context still requires
        external evidence — the exemption must not weaken the anti-hallucination gate.
        """
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            build_external_evidence_reason,
        )

        messages = [
            HumanMessage(content="今天最新的 AI 新闻是什么？"),
            AIMessage(content="All done."),
        ]
        reason = build_external_evidence_reason(messages=messages, records=[])
        assert reason is not None

    def test_internal_task_with_external_hint_still_requires_evidence(self) -> None:
        """An explicit external hint (links/search) suppresses the local-work
        exemption — the user clearly wants outside material."""
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            build_external_evidence_reason,
        )

        messages = [
            HumanMessage(content="分析最新代码改动，并搜索网上的最佳实践"),
            AIMessage(content="All done."),
        ]
        reason = build_external_evidence_reason(messages=messages, records=[])
        assert reason is not None

    def test_no_evidence_required_for_local_test_result_zh(self) -> None:
        """A local test-result query phrased with 'latest' must NOT require external
        evidence — test runs live in the user's own repository, not on the web."""
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            build_external_evidence_reason,
        )

        messages = [
            HumanMessage(content="帮我看看最新的测试结果"),
            AIMessage(content="All done."),
        ]
        reason = build_external_evidence_reason(messages=messages, records=[])
        assert reason is None

    def test_no_evidence_required_for_local_test_result_en(self) -> None:
        """English equivalent of a local test-result query is also exempted."""
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            build_external_evidence_reason,
        )

        messages = [
            HumanMessage(content="What are the latest test results?"),
            AIMessage(content="All done."),
        ]
        reason = build_external_evidence_reason(messages=messages, records=[])
        assert reason is None

    def test_no_evidence_required_for_local_logs_and_scripts(self) -> None:
        """Local log/script queries are exempted — logs and scripts are workspace
        artifacts, not external material."""
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            build_external_evidence_reason,
        )

        messages = [
            HumanMessage(content="最新日志和脚本的改动情况"),
            AIMessage(content="All done."),
        ]
        reason = build_external_evidence_reason(messages=messages, records=[])
        assert reason is None

    def test_evidence_still_required_for_external_price_query(self) -> None:
        """A genuine freshness query about market data must NOT be exempted —
        '金价/price' carries no local-work signal, so the anti-hallucination
        gate must keep forcing external evidence."""
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            build_external_evidence_reason,
        )

        messages = [
            HumanMessage(content="今天最新金价是多少"),
            AIMessage(content="All done."),
        ]
        reason = build_external_evidence_reason(messages=messages, records=[])
        assert reason is not None

    def test_returns_true_for_successful_mcp_direct_fc_tool(self) -> None:
        """A successful Direct FC MCP tool call (mcp__{server}__{tool}) is external evidence."""
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            has_external_evidence,
        )

        record = CallRecord(
            tool_name="mcp__12306__get_current_date",
            args_hash="d1",
            args={},
            success_level=SuccessLevel.FULL_SUCCESS,
        )
        assert has_external_evidence([record]) is True

    def test_returns_false_for_failed_mcp_direct_fc_tool(self) -> None:
        """A failed Direct FC MCP tool call must not count as external evidence."""
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            has_external_evidence,
        )

        record = CallRecord(
            tool_name="mcp__12306__get_current_date",
            args_hash="d1",
            args={},
            success_level=SuccessLevel.FAILURE,
        )
        assert has_external_evidence([record]) is False

    def test_returns_false_for_plain_tool_matching_mcp_prefix_only(self) -> None:
        """A non-MCP tool that merely starts with 'mcp' (no __delimiter) is not evidence."""
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            has_external_evidence,
        )

        record = CallRecord(
            tool_name="mcp_config_tool",
            args_hash="m1",
            args={},
            success_level=SuccessLevel.FULL_SUCCESS,
        )
        assert has_external_evidence([record]) is False

    def test_returns_false_for_intercepted_mcp_direct_fc_tool(self) -> None:
        """An intercepted Direct FC MCP call (success_level=None) is NOT evidence —
        an unexecuted tool provides no external data."""
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            has_external_evidence,
        )

        record = CallRecord(
            tool_name="mcp__12306__query_tickets",
            args_hash="d1",
            args={},
            success_level=None,
        )
        assert has_external_evidence([record]) is False

    def test_returns_false_for_intercepted_mcp_ptc_bash(self) -> None:
        """An intercepted MCP PTC bash call (success_level=None) is NOT evidence."""
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            has_external_evidence,
        )

        record = CallRecord(
            tool_name="bash_code_execute_tool",
            args_hash="mcp1",
            args={"command": "from skills.mcp_12306_skill import get_tickets"},
            success_level=None,
        )
        assert has_external_evidence([record]) is False

    def test_returns_false_for_intercepted_builtin_evidence_tool(self) -> None:
        """An intercepted built-in evidence tool (success_level=None) is NOT evidence."""
        from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
            has_external_evidence,
        )

        record = CallRecord(
            tool_name="web_search_tool",
            args_hash="s1",
            args={"query": "today's news"},
            success_level=None,
        )
        assert has_external_evidence([record]) is False


class TestCompletionGuardTodoChecklist:
    """Test completion_guard_checklist todo items integration and blocked guidance."""

    def test_build_checklist_with_blocked_and_actionable_todos(self, tmp_path: Path) -> None:
        from myrm_agent_harness.agent.meta_tools.progress.schemas import (
            TodoItem,
            TodoStatus,
            TodoStore,
        )
        from myrm_agent_harness.agent.meta_tools.progress.storage import (
            write_todos_sync_to_workspace,
        )

        store = TodoStore(
            goal="Test todo checklist",
            todos=[
                TodoItem(id="t1", content="fetch remote resource", status=TodoStatus.BLOCKED),
                TodoItem(id="t2", content="implement core logic", status=TodoStatus.IN_PROGRESS),
                TodoItem(id="t3", content="done item", status=TodoStatus.COMPLETED),
            ],
        )
        write_todos_sync_to_workspace(str(tmp_path), store)

        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="w1",
                args={"path": "/tmp/test.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            )
        ]
        checklist, has_critical = build_checklist(records, workspace_root=str(tmp_path))
        assert has_critical is True
        assert "CRITICAL: You have incomplete todos in your task list!" in checklist
        assert "Todo t1: fetch remote resource (Status: blocked)" in checklist
        assert "Todo t2: implement core logic (Status: in_progress)" in checklist
        assert "You MUST complete actionable todos and call `todo_write(merge=true)` before finishing." in checklist
        assert "For blocked todos that cannot be completed due to external constraints, mark them as 'cancelled'" in checklist

    def test_build_checklist_with_only_blocked_todos(self, tmp_path: Path) -> None:
        from myrm_agent_harness.agent.meta_tools.progress.schemas import (
            TodoItem,
            TodoStatus,
            TodoStore,
        )
        from myrm_agent_harness.agent.meta_tools.progress.storage import (
            write_todos_sync_to_workspace,
        )

        store = TodoStore(
            goal="Test blocked-only checklist",
            todos=[
                TodoItem(id="t1", content="external service down", status=TodoStatus.BLOCKED),
                TodoItem(id="t2", content="done item", status=TodoStatus.COMPLETED),
            ],
        )
        write_todos_sync_to_workspace(str(tmp_path), store)

        records = [
            CallRecord(
                tool_name="file_write_tool",
                args_hash="w1",
                args={"path": "/tmp/test.py"},
                success_level=SuccessLevel.FULL_SUCCESS,
            )
        ]
        checklist, has_critical = build_checklist(records, workspace_root=str(tmp_path))
        assert has_critical is True
        assert "CRITICAL: You have incomplete todos in your task list!" in checklist
        assert "Todo t1: external service down (Status: blocked)" in checklist
        # Should NOT prompt to complete actionable todos since there are none
        assert "You MUST complete actionable todos" not in checklist
        # Should prompt to mark blocked as cancelled
        assert "For blocked todos that cannot be completed due to external constraints, mark them as 'cancelled'" in checklist


class TestCompletionGuardUnwrittenDeliverablesAndAutoStaging:
    """Test unwritten deliverable gate and auto-staging integration in CompletionGuard."""

    def setup_method(self) -> None:
        self.guard = CompletionGuard(max_rejections=2)
        reset_completion_guard()

    @pytest.mark.asyncio
    async def test_blocks_completion_when_substantive_code_without_write(self, tmp_path: Path) -> None:
        code_msg = (
            "Here is the implementation:\n"
            "```python\n"
            "# filename: app/server.py\n"
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            "\n"
            "@app.get('/health')\n"
            "def health():\n"
            "    return {'status': 'ok'}\n"
            "```\n"
            "All done!"
        )
        state = _make_state([
            HumanMessage(content="Please implement the FastAPI server."),
            AIMessage(content=code_msg),
        ])
        runtime = {"configurable": {"context": {"workspace_root": str(tmp_path)}}}

        mock_loop_guard = MagicMock()
        mock_loop_guard._window = []

        with patch(LOOP_GUARD_PATCH, return_value=mock_loop_guard):
            res = await self.guard.aafter_model(state, runtime)

        assert res is not None
        patched_msg = res["messages"][0]
        assert len(patched_msg.tool_calls) == 1
        tc = patched_msg.tool_calls[0]
        assert tc["name"] == COMPLETION_CHECK_TOOL_NAME
        assert "Substantial unpersisted deliverables detected" in str(tc["args"].get("deliverable_write_reason", ""))

    @pytest.mark.asyncio
    async def test_forced_finish_triggers_auto_staging(self, tmp_path: Path) -> None:
        code_msg = (
            "```python\n"
            "# filename: app/calc.py\n"
            "def add(a, b):\n"
            "    return a + b\n"
            "\n"
            "def sub(a, b):\n"
            "    return a - b\n"
            "```"
        )
        state = _make_state([
            HumanMessage(content="Create calculator"),
            AIMessage(content=code_msg),
        ])
        runtime = {"configurable": {"context": {"workspace_root": str(tmp_path)}}}

        mock_loop_guard = MagicMock()
        mock_loop_guard._window = []

        with patch(LOOP_GUARD_PATCH, return_value=mock_loop_guard):
            # First rejection
            res1 = await self.guard.aafter_model(state, runtime)
            assert res1 is not None

            # Second rejection
            res2 = await self.guard.aafter_model(state, runtime)
            assert res2 is not None

            # Third attempt triggers max_rejections (max_rejections=2) -> forced finish
            res3 = await self.guard.aafter_model(state, runtime)
            assert res3 is not None
            final_msg = res3["messages"][0]
            assert final_msg.tool_calls[0]["args"].get("force_fail") is True
            staged = final_msg.tool_calls[0]["args"].get("staged_artifacts")
            assert staged is not None
            assert len(staged) == 1
            assert staged[0]["original_hint"] == "app/calc.py"

            # Verify actual file staged in sandbox workspace
            staged_dir = tmp_path / ".myrm" / "staged_artifacts"
            assert staged_dir.exists()
            staged_files = list(staged_dir.glob("*_calc.py"))
            assert len(staged_files) == 1
            assert "def add(a, b):" in staged_files[0].read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_pedagogical_snippet_not_blocked(self, tmp_path: Path) -> None:
        snippet_msg = (
            "Here is how quicksort works in theory:\n"
            "```python\n"
            "def qs(arr):\n"
            "    if not arr: return []\n"
            "    return qs([x for x in arr[1:] if x < arr[0]]) + [arr[0]] + qs([x for x in arr[1:] if x >= arr[0]])\n"
            "```\n"
            "Let me know if you have questions!"
        )
        state = _make_state([
            HumanMessage(content="什么是快速排序算法？请解释一下原理"),
            AIMessage(content=snippet_msg),
        ])
        runtime = {"configurable": {"context": {"workspace_root": str(tmp_path)}}}

        mock_loop_guard = MagicMock()
        mock_loop_guard._window = []

        with patch(LOOP_GUARD_PATCH, return_value=mock_loop_guard):
            res = await self.guard.aafter_model(state, runtime)

        # No critical error blocking for short educational explanation
        assert res is None


class TestCompletionGuardQueryGroundingIntegration:
    """Integration tests for query grounding enforcement in CompletionGuard."""

    def setup_method(self) -> None:
        self.guard = CompletionGuard()
        reset_completion_guard()

    @pytest.mark.asyncio
    async def test_query_intent_without_tool_calls_blocks_with_query_grounding_reason(
        self, tmp_path: Path
    ) -> None:
        state = _make_state([
            HumanMessage(content="查一下订单 OD-10086 的发货状态"),
            AIMessage(content="订单 OD-10086 已经发货了，预计明天送达。"),
        ])
        runtime = {"configurable": {"context": {"workspace_root": str(tmp_path)}}}

        mock_loop_guard = MagicMock()
        mock_loop_guard._window = []

        with patch(LOOP_GUARD_PATCH, return_value=mock_loop_guard):
            res = await self.guard.aafter_model(state, runtime)

        assert res is not None
        final_msg = res["messages"][0]
        assert final_msg.tool_calls[0]["name"] == COMPLETION_CHECK_TOOL_NAME
        reason = final_msg.tool_calls[0]["args"].get("query_grounding_reason")
        assert reason is not None
        assert "no query or MCP tool was executed" in str(reason)

    @pytest.mark.asyncio
    async def test_multi_entity_query_missing_one_entity_blocks_in_guard(
        self, tmp_path: Path
    ) -> None:
        rec_od = CallRecord(
            tool_name="mcp__erp__query_order",
            args={"order_id": "OD-9921"},
            success_level=SuccessLevel.FULL_SUCCESS,
        )
        state = _make_state([
            HumanMessage(content="帮我查一下订单 OD-9921 的状态，顺便看一下工单 TK-8802 的进度"),
            AIMessage(content="订单 OD-9921 已发货，工单 TK-8802 正在处理中。"),
        ])
        runtime = {"configurable": {"context": {"workspace_root": str(tmp_path)}}}

        mock_loop_guard = MagicMock()
        mock_loop_guard._window = [rec_od]

        with patch(LOOP_GUARD_PATCH, return_value=mock_loop_guard):
            res = await self.guard.aafter_model(state, runtime)

        assert res is not None
        final_msg = res["messages"][0]
        assert final_msg.tool_calls[0]["name"] == COMPLETION_CHECK_TOOL_NAME
        reason = final_msg.tool_calls[0]["args"].get("query_grounding_reason")
        assert reason is not None
        assert "TK-8802" in str(reason)

    @pytest.mark.asyncio
    async def test_multi_entity_query_missing_one_with_honest_negative_passes_guard(
        self, tmp_path: Path
    ) -> None:
        rec_od = CallRecord(
            tool_name="mcp__erp__query_order",
            args={"order_id": "OD-9921"},
            success_level=SuccessLevel.FULL_SUCCESS,
        )
        state = _make_state([
            HumanMessage(content="帮我查一下订单 OD-9921 的状态，顺便看一下工单 TK-8802 的进度"),
            AIMessage(
                content="订单 OD-9921 已发货；系统查询显示工单 TK-8802 暂未查询到对应处理进度。"
            ),
        ])
        runtime = {"configurable": {"context": {"workspace_root": str(tmp_path)}}}

        mock_loop_guard = MagicMock()
        mock_loop_guard._window = [rec_od]

        with patch(LOOP_GUARD_PATCH, return_value=mock_loop_guard):
            res = await self.guard.aafter_model(state, runtime)

        assert res is None

    @pytest.mark.asyncio
    async def test_multi_entity_query_all_grounded_passes_guard(
        self, tmp_path: Path
    ) -> None:
        rec_od = CallRecord(
            tool_name="mcp__erp__query_order",
            args={"order_id": "OD-9921"},
            success_level=SuccessLevel.FULL_SUCCESS,
        )
        rec_tk = CallRecord(
            tool_name="mcp__itsm__query_ticket",
            args={"ticket_id": "TK-8802"},
            success_level=SuccessLevel.FULL_SUCCESS,
        )
        state = _make_state([
            HumanMessage(content="帮我查一下订单 OD-9921 的状态，顺便看一下工单 TK-8802 的进度"),
            AIMessage(content="订单 OD-9921 已发货，工单 TK-8802 处理中。"),
        ])
        runtime = {"configurable": {"context": {"workspace_root": str(tmp_path)}}}

        mock_loop_guard = MagicMock()
        mock_loop_guard._window = [rec_od, rec_tk]

        with patch(LOOP_GUARD_PATCH, return_value=mock_loop_guard):
            res = await self.guard.aafter_model(state, runtime)

        assert res is None



