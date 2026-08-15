"""Additional tests for _tool_guards — branch coverage for rare paths.

Covers pre-call guard branches (e-stop KILL_ALL, turn budget BREAK,
frequency BREAK/WARN, loop feed, sandbox boundary, circuit breaker "any",
tracker-backed loop feed, ToolStuck re-raise) and post-call guard branches
(steering activation, empty output, rules append, post sandbox boundary,
freq WARN warning assembly, non-ToolMessage passthrough, completion
verification tagging).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.middlewares.tooling._tool_guards import (
    PreCallResult,
    run_post_call_guards,
    run_pre_call_guards,
)
from myrm_agent_harness.agent.security.guards.context_budget import BudgetAction
from myrm_agent_harness.agent.security.guards.estop import EStopLevel, EStopState
from myrm_agent_harness.agent.security.guards.frequency_guard import FrequencyAction
from myrm_agent_harness.agent.security.guards.loop_guard import LoopAction
from myrm_agent_harness.agent.security.guards.tool_turn_budget_guard import TurnBudgetAction


def _request(args: dict[str, object] | None = None) -> MagicMock:
    request = MagicMock()
    request.tool_call = {"args": args or {}}
    request.tool = MagicMock()
    return request


def _loop_guard(verdict: object, metrics: object | None = None) -> MagicMock:
    guard = MagicMock()
    guard.pre_check.return_value = verdict
    if metrics is not None:
        guard.get_metrics.return_value = metrics
    return guard


def _metrics(total_calls: int = 1) -> MagicMock:
    m = MagicMock()
    m.total_calls = total_calls
    m.detection_rate = 0.0
    m.avg_streak = 0
    m.param_change_rate = 0.0
    m.effective_follow_rate = 0.0
    return m


def _allow_verdict() -> MagicMock:
    v = MagicMock()
    v.action = LoopAction.ALLOW
    v.backoff_hint = None
    return v


def _freq_allow() -> MagicMock:
    v = MagicMock()
    v.action = FrequencyAction.ALLOW
    return v


def _base_pre_patches():
    """Patches needed to reach loop/freq guards in run_pre_call_guards."""
    return (
        patch(
            "myrm_agent_harness.agent.hooks.executor.fire_hook",
            new_callable=AsyncMock,
            return_value=MagicMock(blocked=False, updated_input=None),
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_estop",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling._tool_guards._check_circuit_breaker",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_token_tracker",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling._tool_guards.record_decision",
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_steering_token",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_trust_attenuation",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_tool_params_pii",
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_frequency_guard",
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_tool_turn_budget_guard",
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling._tool_guards.resolve_turn_budget_units",
            return_value=1,
        ),
    )


class TestPreCallRareBranches:
    @pytest.mark.asyncio
    async def test_estop_kill_all_prefixes_emergency(self) -> None:
        estop = EStopState(level=EStopLevel.KILL_ALL, reason="user requested", activated_at=0.0, activated_by="user")
        with (
            patch(
                "myrm_agent_harness.agent.hooks.executor.fire_hook",
                new_callable=AsyncMock,
                return_value=MagicMock(blocked=False, updated_input=None),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_estop",
                return_value=estop,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.record_decision",
            ),
        ):
            result = await run_pre_call_guards(_request(), "bash_code_execute_tool", "c1", {})
        assert isinstance(result, ToolMessage)
        assert result.content.startswith("EMERGENCY:")

    @pytest.mark.asyncio
    async def test_circuit_breaker_any_blocks(self) -> None:
        registry = MagicMock()
        registry.get_all.return_value = {"any"}
        with (
            patch(
                "myrm_agent_harness.agent.hooks.executor.fire_hook",
                new_callable=AsyncMock,
                return_value=MagicMock(blocked=False, updated_input=None),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_terminal_errors",
                return_value=registry,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.record_decision",
            ),
        ):
            result = await run_pre_call_guards(_request(), "web_search_tool", "c2", {})
        assert isinstance(result, ToolMessage)
        assert "circuit breaker" in result.content.lower()

    @pytest.mark.asyncio
    async def test_turn_budget_break_returns_error(self) -> None:
        verdict = MagicMock()
        verdict.action = TurnBudgetAction.BREAK
        verdict.reason = "Turn budget exhausted"
        verdict.tool_count = 5
        verdict.tool_limit = 5
        verdict.tool_remaining = 0
        budget_guard = MagicMock()
        budget_guard.check.return_value = verdict
        freq_guard = MagicMock()
        freq_guard.check.return_value = _freq_allow()
        with (
            patch(
                "myrm_agent_harness.agent.hooks.executor.fire_hook",
                new_callable=AsyncMock,
                return_value=MagicMock(blocked=False, updated_input=None),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_estop",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards._check_circuit_breaker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_token_tracker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_tool_turn_budget_guard",
                return_value=budget_guard,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.resolve_turn_budget_units",
                return_value=1,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_frequency_guard",
                return_value=freq_guard,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.record_decision",
            ),
        ):
            result = await run_pre_call_guards(
                _request(),
                "bash_code_execute_tool",
                "c3",
                {},
                get_loop_guard_fn=lambda: _loop_guard(_allow_verdict()),
            )
        assert isinstance(result, ToolMessage)
        assert "Turn budget exhausted" in result.content

    @pytest.mark.asyncio
    async def test_frequency_break_returns_error(self) -> None:
        verdict = MagicMock()
        verdict.action = FrequencyAction.BREAK
        verdict.reason = "Too many calls"
        verdict.global_count = 10
        verdict.global_limit = 10
        verdict.global_remaining = 0
        verdict.tool_count = 3
        verdict.tool_limit = 3
        verdict.tool_remaining = 0
        freq_guard = MagicMock()
        freq_guard.check.return_value = verdict
        budget_guard = MagicMock()
        budget_guard.check.return_value = MagicMock(action=TurnBudgetAction.ALLOW)
        with (
            patch(
                "myrm_agent_harness.agent.hooks.executor.fire_hook",
                new_callable=AsyncMock,
                return_value=MagicMock(blocked=False, updated_input=None),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_estop",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards._check_circuit_breaker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_token_tracker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_tool_turn_budget_guard",
                return_value=budget_guard,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.resolve_turn_budget_units",
                return_value=1,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_frequency_guard",
                return_value=freq_guard,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.record_decision",
            ),
        ):
            result = await run_pre_call_guards(
                _request(),
                "bash_code_execute_tool",
                "c4",
                {},
                get_loop_guard_fn=lambda: _loop_guard(_allow_verdict()),
            )
        assert isinstance(result, ToolMessage)
        assert "Too many calls" in result.content

    @pytest.mark.asyncio
    async def test_loop_guard_feed_output_tokens_when_tracker_has_last_call(self) -> None:
        tracker = MagicMock()
        tracker.usage.last_call.completion_tokens = 42
        tracker.call_count = 7
        loop_guard = MagicMock()
        loop_guard.pre_check.return_value = _allow_verdict()
        loop_guard.get_metrics.return_value = _metrics()
        freq_guard = MagicMock()
        freq_guard.check.return_value = _freq_allow()
        budget_guard = MagicMock()
        budget_guard.check.return_value = MagicMock(action=TurnBudgetAction.ALLOW)
        with (
            patch(
                "myrm_agent_harness.agent.hooks.executor.fire_hook",
                new_callable=AsyncMock,
                return_value=MagicMock(blocked=False, updated_input=None),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_estop",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards._check_circuit_breaker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_token_tracker",
                return_value=tracker,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_tool_turn_budget_guard",
                return_value=budget_guard,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.resolve_turn_budget_units",
                return_value=1,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_frequency_guard",
                return_value=freq_guard,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.record_decision",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_steering_token",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_trust_attenuation",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_tool_params_pii",
                return_value=None,
            ),
        ):
            result = await run_pre_call_guards(
                _request(),
                "bash_code_execute_tool",
                "c5",
                {},
                get_loop_guard_fn=lambda: loop_guard,
            )
        loop_guard.feed_output_tokens.assert_called_once_with(7, 42, has_tool_call=True)
        assert isinstance(result, PreCallResult)

    @pytest.mark.asyncio
    async def test_sandbox_boundary_loop_kind_emits_special_event(self) -> None:
        verdict = MagicMock()
        verdict.action = LoopAction.BREAK
        verdict.reason = "Escaped sandbox"
        verdict.backoff_hint = "none"
        verdict.loop_kind = "sandbox_boundary"
        mock_emit = AsyncMock()
        with (
            patch(
                "myrm_agent_harness.agent.hooks.executor.fire_hook",
                new_callable=AsyncMock,
                return_value=MagicMock(blocked=False, updated_input=None),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_estop",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards._check_circuit_breaker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_token_tracker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards._emit_loop_guard_event",
                mock_emit,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.record_decision",
            ),
        ):
            result = await run_pre_call_guards(
                _request(),
                "bash_code_execute_tool",
                "c6",
                {},
                get_loop_guard_fn=lambda: _loop_guard(verdict),
            )
        mock_emit.assert_called_once_with("sandbox_boundary", "bash_code_execute_tool", "Escaped sandbox", "error")
        assert isinstance(result, ToolMessage)

    @pytest.mark.asyncio
    async def test_pre_check_unknown_exception_re_raises(self) -> None:
        guard = MagicMock()
        guard.pre_check.side_effect = RuntimeError("boom")

        class _LoopGuard:
            def pre_check(self, *a, **kw):
                raise RuntimeError("boom")

            def get_metrics(self):
                return _metrics()

        with (
            patch(
                "myrm_agent_harness.agent.hooks.executor.fire_hook",
                new_callable=AsyncMock,
                return_value=MagicMock(blocked=False, updated_input=None),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_estop",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards._check_circuit_breaker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_token_tracker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.record_decision",
            ),
            pytest.raises(RuntimeError),
        ):
            await run_pre_call_guards(
                _request(),
                "bash_code_execute_tool",
                "c7",
                {},
                get_loop_guard_fn=lambda: _LoopGuard(),
            )

    @pytest.mark.asyncio
    async def test_trust_attenuation_blocks(self) -> None:
        with (
            patch(
                "myrm_agent_harness.agent.hooks.executor.fire_hook",
                new_callable=AsyncMock,
                return_value=MagicMock(blocked=False, updated_input=None),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_estop",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards._check_circuit_breaker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_token_tracker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_tool_turn_budget_guard",
                return_value=MagicMock(
                    check=MagicMock(return_value=MagicMock(action=TurnBudgetAction.ALLOW)),
                    record=MagicMock(),
                ),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.resolve_turn_budget_units",
                return_value=1,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_frequency_guard",
                return_value=MagicMock(check=MagicMock(return_value=_freq_allow())),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.record_decision",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_steering_token",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_trust_attenuation",
                return_value="Trust attenuated: agent changed",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_tool_params_pii",
                return_value=None,
            ),
        ):
            result = await run_pre_call_guards(
                _request(),
                "bash_code_execute_tool",
                "c8",
                {},
                get_loop_guard_fn=lambda: _loop_guard(_allow_verdict()),
            )
        assert isinstance(result, ToolMessage)
        assert "Trust attenuated" in result.content

    @pytest.mark.asyncio
    async def test_pii_params_blocks(self) -> None:
        with (
            patch(
                "myrm_agent_harness.agent.hooks.executor.fire_hook",
                new_callable=AsyncMock,
                return_value=MagicMock(blocked=False, updated_input=None),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_estop",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards._check_circuit_breaker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_token_tracker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_tool_turn_budget_guard",
                return_value=MagicMock(
                    check=MagicMock(return_value=MagicMock(action=TurnBudgetAction.ALLOW)),
                    record=MagicMock(),
                ),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.resolve_turn_budget_units",
                return_value=1,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_frequency_guard",
                return_value=MagicMock(check=MagicMock(return_value=_freq_allow())),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.record_decision",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_steering_token",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_trust_attenuation",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_tool_params_pii",
                return_value="PII detected in params",
            ),
        ):
            result = await run_pre_call_guards(
                _request(),
                "bash_code_execute_tool",
                "c9",
                {},
                get_loop_guard_fn=lambda: _loop_guard(_allow_verdict()),
            )
        assert isinstance(result, ToolMessage)
        assert "PII detected" in result.content

    @pytest.mark.asyncio
    async def test_steering_active_skips(self) -> None:
        steering = MagicMock()
        steering.is_active = True
        with (
            patch(
                "myrm_agent_harness.agent.hooks.executor.fire_hook",
                new_callable=AsyncMock,
                return_value=MagicMock(blocked=False, updated_input=None),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_estop",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards._check_circuit_breaker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_token_tracker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_tool_turn_budget_guard",
                return_value=MagicMock(
                    check=MagicMock(return_value=MagicMock(action=TurnBudgetAction.ALLOW)),
                    record=MagicMock(),
                ),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.resolve_turn_budget_units",
                return_value=1,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_frequency_guard",
                return_value=MagicMock(check=MagicMock(return_value=_freq_allow())),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.record_decision",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_steering_token",
                return_value=steering,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_trust_attenuation",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_tool_params_pii",
                return_value=None,
            ),
        ):
            result = await run_pre_call_guards(
                _request(),
                "bash_code_execute_tool",
                "c10",
                {},
                get_loop_guard_fn=lambda: _loop_guard(_allow_verdict()),
            )
        assert isinstance(result, ToolMessage)
        assert "skipped" in result.content.lower()

    @pytest.mark.asyncio
    async def test_invalid_tool_returns_invalid_tool_error(self) -> None:
        request = _request()
        request.tool = None
        with (
            patch(
                "myrm_agent_harness.agent.hooks.executor.fire_hook",
                new_callable=AsyncMock,
                return_value=MagicMock(blocked=False, updated_input=None),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_estop",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards._check_circuit_breaker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_token_tracker",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_tool_turn_budget_guard",
                return_value=MagicMock(
                    check=MagicMock(return_value=MagicMock(action=TurnBudgetAction.ALLOW)),
                    record=MagicMock(),
                ),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.resolve_turn_budget_units",
                return_value=1,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_frequency_guard",
                return_value=MagicMock(check=MagicMock(return_value=_freq_allow())),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.record_decision",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_steering_token",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_trust_attenuation",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_tool_params_pii",
                return_value=None,
            ),
        ):
            result = await run_pre_call_guards(
                request,
                "ghost_tool",
                "c11",
                {},
                get_loop_guard_fn=lambda: _loop_guard(_allow_verdict()),
            )
        assert isinstance(result, ToolMessage)
        assert "not a valid tool" in result.content


class TestPostCallRareBranches:
    def _post_patches(self, budget_action: BudgetAction = BudgetAction.OK):
        budget_verdict = MagicMock()
        budget_verdict.action = budget_action
        budget_verdict.reason = "budget reason"
        budget_verdict.content = "truncated content"
        return (
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_context_budget_guard",
                return_value=MagicMock(check_and_truncate=MagicMock(return_value=budget_verdict)),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.record_decision",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.emit_archive_restore_block_status",
                new_callable=AsyncMock,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._mutation_verifier.record_mutation_result",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.run_content_validation",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.security.guards.taint_tracker.get_taint_tracker",
                return_value=MagicMock(record_tool_output=MagicMock()),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_tool_result_pii",
            ),
            patch(
                "myrm_agent_harness.agent.workspace_rules.tracker.check_and_append_rules",
                return_value=None,
            ),
            patch(
                "myrm_agent_harness.agent.hooks.executor.fire_hook",
                new_callable=AsyncMock,
                return_value=MagicMock(blocked=False, all_succeeded=True),
            ),
        )

    def _enter_patches(self, *extra):
        from contextlib import ExitStack

        stack = ExitStack()
        for p in self._post_patches():
            stack.enter_context(p)
        for p in extra:
            stack.enter_context(p)
        return stack

    @pytest.mark.asyncio
    async def test_non_tool_message_passthrough(self) -> None:
        sentinel = MagicMock()
        result = await run_post_call_guards(
            sentinel,
            "tool",
            "c",
            {},
            loop_guard=MagicMock(),
            loop_verdict=_allow_verdict(),
            freq_guard=MagicMock(),
            freq_verdict=_freq_allow(),
            steering_token=None,
        )
        assert result is sentinel

    @pytest.mark.asyncio
    async def test_empty_output_replaced(self) -> None:
        post_verdict = MagicMock()
        post_verdict.action = LoopAction.ALLOW
        loop_guard = MagicMock()
        loop_guard.record_result.return_value = post_verdict
        freq_guard = MagicMock()
        with (
            self._enter_patches(
                patch(
                    "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_tool_result_pii",
                    return_value=(ToolMessage(content="(no output)", name="t", tool_call_id="c"), "(no output)"),
                ),
            )
        ):
            msg = ToolMessage(content="", name="t", tool_call_id="c")
            result = await run_post_call_guards(
                msg,
                "t",
                "c",
                {},
                loop_guard=loop_guard,
                loop_verdict=_allow_verdict(),
                freq_guard=freq_guard,
                freq_verdict=_freq_allow(),
                steering_token=None,
            )
        assert "(no output)" in result.content

    @pytest.mark.asyncio
    async def test_rules_append_appended_to_content(self) -> None:
        post_verdict = MagicMock()
        post_verdict.action = LoopAction.ALLOW
        loop_guard = MagicMock()
        loop_guard.record_result.return_value = post_verdict
        freq_guard = MagicMock()
        with (
            self._enter_patches(
                patch(
                    "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_tool_result_pii",
                    return_value=(ToolMessage(content="output", name="t", tool_call_id="c"), "output"),
                ),
                patch(
                    "myrm_agent_harness.agent.workspace_rules.tracker.check_and_append_rules",
                    return_value="\nRule: do not delete",
                ),
            )
        ):
            msg = ToolMessage(content="output", name="t", tool_call_id="c")
            result = await run_post_call_guards(
                msg,
                "t",
                "c",
                {},
                loop_guard=loop_guard,
                loop_verdict=_allow_verdict(),
                freq_guard=freq_guard,
                freq_verdict=_freq_allow(),
                steering_token=None,
            )
        assert "Rule: do not delete" in result.content

    @pytest.mark.asyncio
    async def test_post_sandbox_boundary_emits_special_event(self) -> None:
        post_verdict = MagicMock()
        post_verdict.action = LoopAction.BREAK
        post_verdict.reason = "boundary"
        post_verdict.loop_kind = "sandbox_boundary"
        loop_guard = MagicMock()
        loop_guard.record_result.return_value = post_verdict
        freq_guard = MagicMock()
        mock_emit = AsyncMock()
        with (
            self._enter_patches(
                patch(
                    "myrm_agent_harness.agent.middlewares.tooling._tool_guards._emit_loop_guard_event",
                    mock_emit,
                ),
                patch(
                    "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_tool_result_pii",
                    return_value=(ToolMessage(content="o", name="t", tool_call_id="c"), "o"),
                ),
            )
        ):
            msg = ToolMessage(content="o", name="t", tool_call_id="c")
            await run_post_call_guards(
                msg,
                "t",
                "c",
                {},
                loop_guard=loop_guard,
                loop_verdict=_allow_verdict(),
                freq_guard=freq_guard,
                freq_verdict=_freq_allow(),
                steering_token=None,
            )
        mock_emit.assert_called_once_with("sandbox_boundary", "t", "boundary", "error")

    @pytest.mark.asyncio
    async def test_freq_warn_warning_assembled(self) -> None:
        post_verdict = MagicMock()
        post_verdict.action = LoopAction.ALLOW
        loop_guard = MagicMock()
        loop_guard.record_result.return_value = post_verdict
        freq_guard = MagicMock()
        freq_verdict = MagicMock()
        freq_verdict.action = FrequencyAction.WARN
        freq_verdict.reason = "approaching limit"
        freq_verdict.global_count = 8
        freq_verdict.global_limit = 10
        freq_verdict.global_remaining = 2
        freq_verdict.tool_count = 1
        freq_verdict.tool_limit = 5
        freq_verdict.tool_remaining = 4
        with self._enter_patches(
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_tool_result_pii",
                return_value=(ToolMessage(content="o", name="t", tool_call_id="c"), "o"),
            ),
        ):
            msg = ToolMessage(content="o", name="t", tool_call_id="c")
            result = await run_post_call_guards(
                msg,
                "t",
                "c",
                {},
                loop_guard=loop_guard,
                loop_verdict=_allow_verdict(),
                freq_guard=freq_guard,
                freq_verdict=freq_verdict,
                steering_token=None,
            )
        assert "Frequency warning" in result.content
    @pytest.mark.asyncio
    async def test_steering_token_pending_activates(self) -> None:
        steering = MagicMock()
        steering.has_pending = True
        steering.activate = MagicMock()
        post_verdict = MagicMock()
        post_verdict.action = LoopAction.ALLOW
        loop_guard = MagicMock()
        loop_guard.record_result.return_value = post_verdict
        with self._enter_patches(
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_tool_result_pii",
                return_value=(ToolMessage(content="o", name="t", tool_call_id="c"), "o"),
            ),
        ):
            msg = ToolMessage(content="o", name="t", tool_call_id="c")
            await run_post_call_guards(
                msg,
                "t",
                "c",
                {},
                loop_guard=loop_guard,
                loop_verdict=_allow_verdict(),
                freq_guard=MagicMock(),
                freq_verdict=_freq_allow(),
                steering_token=steering,
            )
        steering.activate.assert_called_once()

    @pytest.mark.asyncio
    async def test_completion_verification_tagging(self) -> None:
        post_verdict = MagicMock()
        post_verdict.action = LoopAction.ALLOW
        loop_guard = MagicMock()
        loop_guard.record_result.return_value = post_verdict
        freq_guard = MagicMock()
        with self._enter_patches(
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._tool_guards.check_tool_result_pii",
                return_value=(ToolMessage(content="o", name="bash_code_execute_tool", tool_call_id="c"), "o"),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.completion.completion_guard_checklist.classify_verification",
                return_value="echo",
            ),
        ):
            msg = ToolMessage(content="o", name="bash_code_execute_tool", tool_call_id="c")
            await run_post_call_guards(
                msg,
                "bash_code_execute_tool",
                "c",
                {},
                loop_guard=loop_guard,
                loop_verdict=_allow_verdict(),
                freq_guard=freq_guard,
                freq_verdict=_freq_allow(),
                steering_token=None,
            )
        loop_guard.tag_last_verification.assert_called_once_with("echo")
