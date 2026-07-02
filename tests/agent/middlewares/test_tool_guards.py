"""Tests for _tool_guards module — loop guard UI event emission.

Covers:
1. _emit_loop_guard_event dispatches correct event payload
2. _emit_loop_guard_event swallows exceptions silently
3. run_pre_call_guards emits loop_guard_break on LoopAction.BREAK
4. run_pre_call_guards emits loop_guard_warn on LoopAction.WARN
5. run_post_call_guards emits loop_guard_break on post-execution BREAK
6. run_post_call_guards emits loop_guard_warn on post-execution WARN
7. run_post_call_guards does NOT emit on LoopAction.ALLOW
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.middlewares._tool_guards import (
    PreCallResult,
    _emit_loop_guard_event,
)
from myrm_agent_harness.agent.security.guards.loop_guard_types import (
    LoopAction,
)


# ---------------------------------------------------------------------------
# 1. _emit_loop_guard_event unit tests
# ---------------------------------------------------------------------------


class TestEmitLoopGuardEvent:
    @pytest.mark.asyncio
    async def test_dispatches_correct_payload(self) -> None:
        """Verify dispatch_custom_event receives correct args."""
        mock_dispatch = AsyncMock()
        with patch(
            "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
            mock_dispatch,
        ):
            await _emit_loop_guard_event(
                "loop_guard_warn", "bash_code_execute_tool", "Repetition detected", "warning"
            )

        mock_dispatch.assert_called_once_with(
            "agent_status",
            {
                "step_key": "loop_guard_warn",
                "tool_name": "bash_code_execute_tool",
                "status": "warning",
                "items": [{"text": "Repetition detected"}],
            },
        )

    @pytest.mark.asyncio
    async def test_dispatches_break_event(self) -> None:
        """Verify BREAK events use correct step_key and status."""
        mock_dispatch = AsyncMock()
        with patch(
            "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
            mock_dispatch,
        ):
            await _emit_loop_guard_event(
                "loop_guard_break", "file_write", "No-progress polling", "error"
            )

        mock_dispatch.assert_called_once_with(
            "agent_status",
            {
                "step_key": "loop_guard_break",
                "tool_name": "file_write",
                "status": "error",
                "items": [{"text": "No-progress polling"}],
            },
        )

    @pytest.mark.asyncio
    async def test_swallows_dispatch_exception(self) -> None:
        """dispatch failure must never propagate — core logic unaffected."""
        mock_dispatch = AsyncMock(side_effect=RuntimeError("SSE channel closed"))
        with patch(
            "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
            mock_dispatch,
        ):
            await _emit_loop_guard_event(
                "loop_guard_break", "bash_code_execute_tool", "reason", "error"
            )

    @pytest.mark.asyncio
    async def test_swallows_import_error(self) -> None:
        """Even if the event_utils module has issues, no exception propagates."""
        with patch(
            "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
            side_effect=ImportError("module not found"),
        ):
            await _emit_loop_guard_event(
                "loop_guard_warn", "tool", "reason", "warning"
            )


# ---------------------------------------------------------------------------
# 2. Integration: run_pre_call_guards emits events on BREAK/WARN
# ---------------------------------------------------------------------------


class TestPreCallGuardsEmitEvent:
    """Test that run_pre_call_guards calls _emit_loop_guard_event appropriately."""

    @pytest.mark.asyncio
    async def test_break_emits_loop_guard_break_event(self) -> None:
        """When LoopGuard returns BREAK, _emit_loop_guard_event is called."""
        mock_emit = AsyncMock()
        mock_verdict = MagicMock()
        mock_verdict.action = LoopAction.BREAK
        mock_verdict.reason = "Repetition pattern on bash_tool"
        mock_verdict.backoff_hint = "Try a different approach"
        mock_verdict.loop_kind = "repetition"

        mock_loop_guard = MagicMock()
        mock_loop_guard.pre_check.return_value = mock_verdict
        mock_loop_guard.get_metrics.return_value = MagicMock(
            total_calls=1,
            detection_rate=0,
            avg_streak=0,
            param_change_rate=0,
            effective_follow_rate=0,
        )

        mock_request = MagicMock()
        mock_request.tool_call = {"args": {}}

        mock_hook_result = MagicMock(blocked=False, updated_input=None)

        with (
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards._emit_loop_guard_event",
                mock_emit,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.check_estop",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.get_token_tracker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.hooks.executor.fire_hook",
                new_callable=AsyncMock,
                return_value=mock_hook_result,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards._check_circuit_breaker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.record_decision",
            ),
        ):
            from myrm_agent_harness.agent.middlewares._tool_guards import (
                run_pre_call_guards,
            )

            result = await run_pre_call_guards(
                mock_request,
                "bash_code_execute_tool",
                "call_123",
                {"command": "ls"},
                get_loop_guard_fn=lambda: mock_loop_guard,
            )

        mock_emit.assert_called_once_with(
            "loop_guard_break",
            "bash_code_execute_tool",
            "Repetition pattern on bash_tool",
            "error",
        )
        assert isinstance(result, ToolMessage)
        assert "Repetition pattern" in result.content

    @pytest.mark.asyncio
    async def test_warn_emits_loop_guard_warn_event(self) -> None:
        """When LoopGuard returns WARN, _emit_loop_guard_event is called and execution continues."""
        mock_emit = AsyncMock()
        mock_verdict = MagicMock()
        mock_verdict.action = LoopAction.WARN
        mock_verdict.reason = "Ping-pong oscillation detected"
        mock_verdict.backoff_hint = "Vary your approach"

        mock_loop_guard = MagicMock()
        mock_loop_guard.pre_check.return_value = mock_verdict
        mock_loop_guard.get_metrics.return_value = MagicMock(
            total_calls=1,
            detection_rate=0,
            avg_streak=0,
            param_change_rate=0,
            effective_follow_rate=0,
        )

        mock_freq_verdict = MagicMock()
        mock_freq_verdict.action = MagicMock()
        # Ensure freq verdict action != BREAK and != WARN
        type(mock_freq_verdict.action).__eq__ = lambda self, other: False

        mock_freq_guard = MagicMock()
        mock_freq_guard.check.return_value = mock_freq_verdict

        mock_request = MagicMock()
        mock_request.tool_call = {"args": {"command": "git status"}}
        mock_request.tool = MagicMock()

        mock_hook_result = MagicMock(blocked=False, updated_input=None)

        with (
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards._emit_loop_guard_event",
                mock_emit,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.check_estop",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.get_token_tracker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.hooks.executor.fire_hook",
                new_callable=AsyncMock,
                return_value=mock_hook_result,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards._check_circuit_breaker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.record_decision",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.get_frequency_guard",
                return_value=mock_freq_guard,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.get_steering_token",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.check_trust_attenuation",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.check_tool_params_pii",
                return_value=None,
            ),
        ):
            from myrm_agent_harness.agent.middlewares._tool_guards import (
                run_pre_call_guards,
            )

            result = await run_pre_call_guards(
                mock_request,
                "bash_code_execute_tool",
                "call_456",
                {"command": "git status"},
                get_loop_guard_fn=lambda: mock_loop_guard,
            )

        mock_emit.assert_called_once_with(
            "loop_guard_warn",
            "bash_code_execute_tool",
            "Ping-pong oscillation detected",
            "warning",
        )
        assert isinstance(result, PreCallResult)


# ---------------------------------------------------------------------------
# 3. Integration: run_post_call_guards emits events
# ---------------------------------------------------------------------------


class TestPostCallGuardsEmitEvent:
    """Test that run_post_call_guards calls _emit_loop_guard_event."""

    @pytest.mark.asyncio
    async def test_post_break_emits_event(self) -> None:
        """When loop_guard.record_result returns BREAK, event is emitted."""
        mock_emit = AsyncMock()

        post_verdict = MagicMock()
        post_verdict.action = LoopAction.BREAK
        post_verdict.reason = "Output diminishing pattern"
        post_verdict.backoff_hint = "Check output"

        mock_loop_guard = MagicMock()
        mock_loop_guard.record_result.return_value = post_verdict

        pre_verdict = MagicMock()
        pre_verdict.action = LoopAction.ALLOW
        pre_verdict.backoff_hint = None

        mock_freq_guard = MagicMock()
        mock_freq_guard.record.return_value = None
        mock_freq_verdict = MagicMock()
        type(mock_freq_verdict.action).__eq__ = lambda self, other: False

        result_msg = ToolMessage(
            content="some output",
            name="bash_code_execute_tool",
            tool_call_id="call_789",
            status="success",
        )

        mock_hook_result = MagicMock(blocked=False, all_succeeded=True)

        with (
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards._emit_loop_guard_event",
                mock_emit,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.record_decision",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.emit_archive_restore_block_status",
                new_callable=AsyncMock,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._mutation_verifier.record_mutation_result",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.get_context_budget_guard",
                return_value=MagicMock(
                    check_and_truncate=MagicMock(
                        return_value=MagicMock(
                            action=MagicMock(__eq__=lambda s, o: False)
                        )
                    )
                ),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.run_content_validation",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.security.guards.taint_tracker.get_taint_tracker",
                return_value=MagicMock(record_tool_output=MagicMock()),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.check_tool_result_pii",
                return_value=(result_msg, "some output"),
            ),
            patch(
                "myrm_agent_harness.agent.workspace_rules.tracker.check_and_append_rules",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.hooks.executor.fire_hook",
                new_callable=AsyncMock,
                return_value=mock_hook_result,
            ),
        ):
            from myrm_agent_harness.agent.middlewares._tool_guards import (
                run_post_call_guards,
            )

            await run_post_call_guards(
                result_msg,
                "bash_code_execute_tool",
                "call_789",
                {"command": "ls"},
                loop_guard=mock_loop_guard,
                loop_verdict=pre_verdict,
                freq_guard=mock_freq_guard,
                freq_verdict=mock_freq_verdict,
                steering_token=None,
            )

        mock_emit.assert_called_once_with(
            "loop_guard_break",
            "bash_code_execute_tool",
            "Output diminishing pattern",
            "error",
        )

    @pytest.mark.asyncio
    async def test_post_warn_emits_event(self) -> None:
        """When loop_guard.record_result returns WARN, event is emitted."""
        mock_emit = AsyncMock()

        post_verdict = MagicMock()
        post_verdict.action = LoopAction.WARN
        post_verdict.reason = "Consecutive failures detected"
        post_verdict.backoff_hint = "Check error patterns"

        mock_loop_guard = MagicMock()
        mock_loop_guard.record_result.return_value = post_verdict

        pre_verdict = MagicMock()
        pre_verdict.action = LoopAction.ALLOW
        pre_verdict.backoff_hint = None

        mock_freq_guard = MagicMock()
        mock_freq_guard.record.return_value = None
        mock_freq_verdict = MagicMock()
        type(mock_freq_verdict.action).__eq__ = lambda self, other: False

        result_msg = ToolMessage(
            content="error: permission denied",
            name="file_write",
            tool_call_id="call_999",
            status="error",
        )

        mock_hook_result = MagicMock(blocked=False, all_succeeded=True)

        with (
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards._emit_loop_guard_event",
                mock_emit,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.record_decision",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.emit_archive_restore_block_status",
                new_callable=AsyncMock,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._mutation_verifier.record_mutation_result",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.get_context_budget_guard",
                return_value=MagicMock(
                    check_and_truncate=MagicMock(
                        return_value=MagicMock(
                            action=MagicMock(__eq__=lambda s, o: False)
                        )
                    )
                ),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.run_content_validation",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.security.guards.taint_tracker.get_taint_tracker",
                return_value=MagicMock(record_tool_output=MagicMock()),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.check_tool_result_pii",
                return_value=(result_msg, "error: permission denied"),
            ),
            patch(
                "myrm_agent_harness.agent.workspace_rules.tracker.check_and_append_rules",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.hooks.executor.fire_hook",
                new_callable=AsyncMock,
                return_value=mock_hook_result,
            ),
        ):
            from myrm_agent_harness.agent.middlewares._tool_guards import (
                run_post_call_guards,
            )

            await run_post_call_guards(
                result_msg,
                "file_write",
                "call_999",
                {"path": "/tmp/test.txt"},
                loop_guard=mock_loop_guard,
                loop_verdict=pre_verdict,
                freq_guard=mock_freq_guard,
                freq_verdict=mock_freq_verdict,
                steering_token=None,
            )

        mock_emit.assert_called_once_with(
            "loop_guard_warn",
            "file_write",
            "Consecutive failures detected",
            "warning",
        )

    @pytest.mark.asyncio
    async def test_post_allow_does_not_emit(self) -> None:
        """When loop_guard.record_result returns ALLOW, no event is emitted."""
        mock_emit = AsyncMock()

        post_verdict = MagicMock()
        post_verdict.action = LoopAction.ALLOW
        post_verdict.reason = ""
        post_verdict.backoff_hint = None

        mock_loop_guard = MagicMock()
        mock_loop_guard.record_result.return_value = post_verdict

        pre_verdict = MagicMock()
        pre_verdict.action = LoopAction.ALLOW
        pre_verdict.backoff_hint = None

        mock_freq_guard = MagicMock()
        mock_freq_guard.record.return_value = None
        mock_freq_verdict = MagicMock()
        type(mock_freq_verdict.action).__eq__ = lambda self, other: False

        result_msg = ToolMessage(
            content="success",
            name="bash_code_execute_tool",
            tool_call_id="call_000",
            status="success",
        )

        mock_hook_result = MagicMock(blocked=False, all_succeeded=True)

        with (
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards._emit_loop_guard_event",
                mock_emit,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.record_decision",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.emit_archive_restore_block_status",
                new_callable=AsyncMock,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._mutation_verifier.record_mutation_result",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.get_context_budget_guard",
                return_value=MagicMock(
                    check_and_truncate=MagicMock(
                        return_value=MagicMock(
                            action=MagicMock(__eq__=lambda s, o: False)
                        )
                    )
                ),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.run_content_validation",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.security.guards.taint_tracker.get_taint_tracker",
                return_value=MagicMock(record_tool_output=MagicMock()),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.check_tool_result_pii",
                return_value=(result_msg, "success"),
            ),
            patch(
                "myrm_agent_harness.agent.workspace_rules.tracker.check_and_append_rules",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.hooks.executor.fire_hook",
                new_callable=AsyncMock,
                return_value=mock_hook_result,
            ),
        ):
            from myrm_agent_harness.agent.middlewares._tool_guards import (
                run_post_call_guards,
            )

            await run_post_call_guards(
                result_msg,
                "bash_code_execute_tool",
                "call_000",
                {"command": "echo hi"},
                loop_guard=mock_loop_guard,
                loop_verdict=pre_verdict,
                freq_guard=mock_freq_guard,
                freq_verdict=mock_freq_verdict,
                steering_token=None,
            )

        mock_emit.assert_not_called()
