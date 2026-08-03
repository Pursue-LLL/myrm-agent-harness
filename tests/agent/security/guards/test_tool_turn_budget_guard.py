"""Tests for ToolTurnBudgetGuard per-turn call limits."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.security.guards.tool_turn_budget_guard import (
    ToolTurnBudgetGuard,
    TurnBudgetAction,
    get_tool_turn_budget_guard,
    reset_tool_turn_budget_guard,
)


class TestToolTurnBudgetGuard:
    def test_unlimited_tool_always_allowed(self):
        guard = ToolTurnBudgetGuard(tool_limits={"web_search_tool": 2})
        verdict = guard.check("bash_code_execute_tool", message_id="msg-1")
        assert verdict.action == TurnBudgetAction.ALLOW

    def test_blocks_at_limit_within_same_turn(self):
        guard = ToolTurnBudgetGuard(tool_limits={"web_search_tool": 2})
        guard.record("web_search_tool", message_id="msg-1")
        guard.record("web_search_tool", message_id="msg-1")

        verdict = guard.check("web_search_tool", message_id="msg-1")
        assert verdict.action == TurnBudgetAction.BREAK
        assert verdict.tool_count == 2
        assert verdict.tool_limit == 2
        assert verdict.tool_remaining == 0

    def test_resets_when_message_id_changes(self):
        guard = ToolTurnBudgetGuard(tool_limits={"web_search_tool": 1})
        guard.record("web_search_tool", message_id="msg-1")

        verdict = guard.check("web_search_tool", message_id="msg-2")
        assert verdict.action == TurnBudgetAction.ALLOW
        assert verdict.tool_count == 0

    def test_reset_clears_state(self):
        guard = ToolTurnBudgetGuard(tool_limits={"web_search_tool": 1})
        guard.record("web_search_tool", message_id="msg-1")
        guard.reset()

        verdict = guard.check("web_search_tool", message_id="msg-1")
        assert verdict.action == TurnBudgetAction.ALLOW

    def test_contextvar_reset(self):
        guard = get_tool_turn_budget_guard()
        guard.record("web_search_tool", message_id="msg-ctx")
        reset_tool_turn_budget_guard()
        verdict = guard.check("web_search_tool", message_id="msg-ctx")
        assert verdict.action == TurnBudgetAction.ALLOW

    def test_invalid_tool_limit_raises(self):
        with pytest.raises(ValueError, match="tool_limits values must be positive"):
            ToolTurnBudgetGuard(tool_limits={"web_search_tool": 0})

    def test_record_ignores_unlimited_tools(self):
        guard = ToolTurnBudgetGuard(tool_limits={"web_search_tool": 2})
        guard.record("bash_code_execute_tool", message_id="msg-1")
        assert guard.check("web_search_tool", message_id="msg-1").tool_count == 0

    def test_reset_without_context_guard_is_noop(self):
        reset_tool_turn_budget_guard()


class TestToolTurnBudgetPreCallIntegration:
    @pytest.mark.asyncio
    async def test_run_pre_call_guards_records_attempt_on_allow(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from myrm_agent_harness.agent.middlewares._tool_guards import (
            PreCallResult,
            run_pre_call_guards,
        )
        from myrm_agent_harness.agent.security.guards.tool_turn_budget_guard import (
            ToolTurnBudgetGuard,
        )

        guard = ToolTurnBudgetGuard(tool_limits={"web_search_tool": 2})

        mock_loop_guard = MagicMock()
        mock_loop_verdict = MagicMock()
        mock_loop_verdict.action = MagicMock()
        type(mock_loop_verdict.action).__eq__ = lambda self, other: False
        mock_loop_guard.pre_check.return_value = mock_loop_verdict

        mock_freq_verdict = MagicMock()
        mock_freq_verdict.action = MagicMock()
        type(mock_freq_verdict.action).__eq__ = lambda self, other: False
        mock_freq_guard = MagicMock()
        mock_freq_guard.check.return_value = mock_freq_verdict

        mock_request = MagicMock()
        mock_request.tool_call = {"args": {"questions": ["test"]}}
        mock_request.tool = MagicMock()
        mock_hook_result = MagicMock(blocked=False, updated_input=None)

        with (
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
                "myrm_agent_harness.agent.middlewares._tool_guards.get_frequency_guard",
                return_value=mock_freq_guard,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.get_tool_turn_budget_guard",
                return_value=guard,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_active_message_id",
                return_value="msg-attempt",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.check_trust_attenuation",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.check_tool_params_pii",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.get_steering_token",
                return_value=None,
            ),
        ):
            result = await run_pre_call_guards(
                mock_request,
                "web_search_tool",
                "call-attempt",
                {"questions": ["test"]},
                get_loop_guard_fn=lambda: mock_loop_guard,
            )

        assert isinstance(result, PreCallResult)
        blocked = guard.check("web_search_tool", message_id="msg-attempt")
        assert blocked.tool_count == 1

    @pytest.mark.asyncio
    async def test_run_pre_call_guards_blocks_at_turn_limit(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from langchain_core.messages import ToolMessage

        from myrm_agent_harness.agent.middlewares._tool_guards import run_pre_call_guards
        from myrm_agent_harness.agent.security.guards.tool_turn_budget_guard import (
            ToolTurnBudgetGuard,
        )

        guard = ToolTurnBudgetGuard(tool_limits={"web_search_tool": 1})
        guard.record("web_search_tool", message_id="msg-limit")

        mock_loop_guard = MagicMock()
        mock_loop_verdict = MagicMock()
        mock_loop_verdict.action = MagicMock()
        type(mock_loop_verdict.action).__eq__ = lambda self, other: False
        mock_loop_guard.pre_check.return_value = mock_loop_verdict

        mock_freq_verdict = MagicMock()
        mock_freq_verdict.action = MagicMock()
        type(mock_freq_verdict.action).__eq__ = lambda self, other: False
        mock_freq_guard = MagicMock()
        mock_freq_guard.check.return_value = mock_freq_verdict

        mock_request = MagicMock()
        mock_request.tool_call = {"args": {"questions": ["test"]}}
        mock_request.tool = MagicMock()
        mock_hook_result = MagicMock(blocked=False, updated_input=None)

        with (
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
                "myrm_agent_harness.agent.middlewares._tool_guards.get_frequency_guard",
                return_value=mock_freq_guard,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.get_tool_turn_budget_guard",
                return_value=guard,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_active_message_id",
                return_value="msg-limit",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.check_trust_attenuation",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.check_tool_params_pii",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._tool_guards.get_steering_token",
                return_value=None,
            ),
        ):
            result = await run_pre_call_guards(
                mock_request,
                "web_search_tool",
                "call-limit",
                {"questions": ["test"]},
                get_loop_guard_fn=lambda: mock_loop_guard,
            )

        assert isinstance(result, ToolMessage)
        assert "per-turn budget exceeded" in str(result.content)
