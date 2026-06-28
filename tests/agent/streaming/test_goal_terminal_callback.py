"""Tests for on_goal_terminal callback trigger in stream_recovery.

Validates that the goal terminal callback fires correctly when goals reach
terminal states ('done' or 'budget'), and does NOT fire for other states.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from myrm_agent_harness.agent.goals.types import (
    Goal,
    GoalBudget,
    GoalExecutionSummary,
    GoalStatus,
)
from myrm_agent_harness.agent.streaming.stream_executor import StreamContext


def _make_ctx(
    on_goal_terminal: AsyncMock | None = None,
    goal_provider: AsyncMock | None = None,
) -> StreamContext:
    """Create a minimal StreamContext for testing."""
    return StreamContext(
        agent=MagicMock(),
        agent_input={"messages": []},
        merged_context={"chat_id": "test-session"},
        run_config=MagicMock(),
        stats=MagicMock(),
        message_id="msg-001",
        cancel_token=None,
        steering_token=None,
        source_tracker=MagicMock(),
        output_queue=asyncio.Queue(),
        goal_provider=goal_provider,
        on_goal_terminal=on_goal_terminal,
    )


def _make_goal(status: GoalStatus = GoalStatus.ACTIVE) -> Goal:
    return Goal(
        goal_id="goal-1",
        session_id="test-session",
        objective="Implement feature X",
        status=status,
        budget=GoalBudget(max_tokens=50000),
        turns_used=3,
    )


class TestGoalTerminalCallbackTrigger:
    """Test that on_goal_terminal fires at correct times."""

    @pytest.mark.asyncio
    async def test_callback_fires_on_done_verdict(self):
        """Callback should fire when verdict is 'done'."""
        callback = AsyncMock()
        goal = _make_goal()
        goal_provider = AsyncMock()
        goal_provider.get_active_goal.return_value = goal
        goal_provider.get_goal.return_value = goal
        goal_provider.get_latest_goal.return_value = goal
        goal_provider.is_continuation_suppressed.return_value = False
        goal_provider.account_usage.return_value = MagicMock(
            goal=goal, status_changed=False, budget_exhausted=False
        )
        goal_provider.evaluate_semantic.return_value = MagicMock(passed=True, reason="done")
        goal_provider.record_progress.return_value = goal

        ctx = _make_ctx(on_goal_terminal=callback, goal_provider=goal_provider)

        from myrm_agent_harness.agent.streaming.stream_recovery import (
            StreamRecoveryMixin,
        )

        mixin = StreamRecoveryMixin.__new__(StreamRecoveryMixin)
        mixin._ctx = ctx
        mixin._compactor = AsyncMock()
        mixin.streaming_final_answer = False

        messages: list[BaseMessage] = [
            HumanMessage(content="Do task X"),
            AIMessage(content="I have completed task X successfully."),
        ]

        result = await mixin._handle_goal_continuation(
            collected_messages=messages,
            tools_called_this_turn=True,
            net_tokens_this_turn=1000,
            cost_this_turn=0.05,
            time_this_turn_seconds=10,
        )

        assert result is False

        await asyncio.sleep(0.1)

        callback.assert_called_once()
        call_args = callback.call_args[0]
        assert call_args[0].goal_id == "goal-1"
        assert len(call_args[1]) == 2
        assert isinstance(call_args[2], GoalExecutionSummary)
        assert call_args[2].turns_used == goal.turns_used

    @pytest.mark.asyncio
    async def test_callback_fires_on_budget_verdict(self):
        """Callback should fire when verdict is 'budget' (budget exhausted).

        Budget-limited goals first get a wrap-up turn (should_continue=True).
        Only after the wrap-up prompt has been injected does the next call
        stop and fire the terminal callback.
        """
        callback = AsyncMock()
        goal = _make_goal(status=GoalStatus.BUDGET_LIMITED)
        goal_provider = AsyncMock()
        goal_provider.get_active_goal.return_value = goal
        goal_provider.get_goal.return_value = goal
        goal_provider.get_latest_goal.return_value = goal
        goal_provider.account_usage.return_value = MagicMock(
            goal=goal, status_changed=True, budget_exhausted=True
        )
        goal_provider.record_progress.return_value = goal

        ctx = _make_ctx(on_goal_terminal=callback, goal_provider=goal_provider)

        from myrm_agent_harness.agent.streaming.stream_recovery import (
            StreamRecoveryMixin,
        )

        mixin = StreamRecoveryMixin.__new__(StreamRecoveryMixin)
        mixin._ctx = ctx
        mixin._compactor = AsyncMock()
        mixin.streaming_final_answer = False

        # Include the wrap-up sentinel so check_continuation recognises
        # that the wrap-up turn already happened and emits "budget" verdict.
        from myrm_agent_harness.agent.goals.continuation import _WRAPUP_SENTINEL

        messages: list[BaseMessage] = [
            HumanMessage(content="Continue working"),
            AIMessage(content="Working on it..."),
            HumanMessage(content=f"{_WRAPUP_SENTINEL}\nPlease wrap up.", name="developer"),
            AIMessage(content="Here is the summary..."),
        ]

        result = await mixin._handle_goal_continuation(
            collected_messages=messages,
            tools_called_this_turn=True,
            net_tokens_this_turn=1000,
            cost_this_turn=0.05,
            time_this_turn_seconds=10,
        )

        assert result is False

        await asyncio.sleep(0.1)

        callback.assert_called_once()
        call_args = callback.call_args[0]
        assert call_args[0].goal_id == "goal-1"
        assert isinstance(call_args[2], GoalExecutionSummary)

    @pytest.mark.asyncio
    async def test_callback_not_fired_on_continue(self):
        """Callback should NOT fire when goal continues."""
        callback = AsyncMock()
        goal = _make_goal()
        goal_provider = AsyncMock()
        goal_provider.get_active_goal.return_value = goal
        goal_provider.get_goal.return_value = goal
        goal_provider.get_latest_goal.return_value = goal
        goal_provider.is_continuation_suppressed.return_value = False
        goal_provider.account_usage.return_value = MagicMock(
            goal=goal, status_changed=False, budget_exhausted=False
        )
        goal_provider.evaluate_semantic.return_value = MagicMock(passed=False, reason="not done", parse_failed=False)
        goal_provider.record_progress.return_value = goal

        ctx = _make_ctx(on_goal_terminal=callback, goal_provider=goal_provider)

        from myrm_agent_harness.agent.streaming.stream_recovery import (
            StreamRecoveryMixin,
        )

        mixin = StreamRecoveryMixin.__new__(StreamRecoveryMixin)
        mixin._ctx = ctx
        mixin._compactor = AsyncMock()
        mixin.streaming_final_answer = False

        messages: list[BaseMessage] = [
            HumanMessage(content="Do more work"),
            AIMessage(content="Still working..."),
        ]

        result = await mixin._handle_goal_continuation(
            collected_messages=messages,
            tools_called_this_turn=True,
            net_tokens_this_turn=1000,
            cost_this_turn=0.05,
            time_this_turn_seconds=10,
        )

        assert result is True
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_not_fired_when_none(self):
        """No error when on_goal_terminal is None."""
        goal = _make_goal()
        goal_provider = AsyncMock()
        goal_provider.get_active_goal.return_value = goal
        goal_provider.get_goal.return_value = goal
        goal_provider.get_latest_goal.return_value = goal
        goal_provider.is_continuation_suppressed.return_value = False
        goal_provider.account_usage.return_value = MagicMock(
            goal=goal, status_changed=False, budget_exhausted=False
        )
        goal_provider.evaluate_semantic.return_value = MagicMock(passed=True, reason="done")
        goal_provider.record_progress.return_value = goal

        ctx = _make_ctx(on_goal_terminal=None, goal_provider=goal_provider)

        from myrm_agent_harness.agent.streaming.stream_recovery import (
            StreamRecoveryMixin,
        )

        mixin = StreamRecoveryMixin.__new__(StreamRecoveryMixin)
        mixin._ctx = ctx
        mixin._compactor = AsyncMock()
        mixin.streaming_final_answer = False

        messages: list[BaseMessage] = [
            AIMessage(content="Done!"),
        ]

        result = await mixin._handle_goal_continuation(
            collected_messages=messages,
            tools_called_this_turn=True,
            net_tokens_this_turn=1000,
            cost_this_turn=0.05,
            time_this_turn_seconds=10,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_callback_not_fired_on_cancelled(self):
        """Callback should NOT fire when goal is cancelled."""
        callback = AsyncMock()
        goal = _make_goal()
        goal_provider = AsyncMock()
        goal_provider.get_active_goal.return_value = goal
        goal_provider.get_goal.return_value = goal
        goal_provider.get_latest_goal.return_value = goal
        goal_provider.account_usage.return_value = MagicMock(
            goal=goal, status_changed=False, budget_exhausted=False
        )
        goal_provider.record_progress.return_value = goal

        cancel_token = MagicMock()
        cancel_token.is_cancelled = True

        ctx = _make_ctx(on_goal_terminal=callback, goal_provider=goal_provider)
        ctx.cancel_token = cancel_token

        from myrm_agent_harness.agent.streaming.stream_recovery import (
            StreamRecoveryMixin,
        )

        mixin = StreamRecoveryMixin.__new__(StreamRecoveryMixin)
        mixin._ctx = ctx
        mixin._compactor = AsyncMock()
        mixin.streaming_final_answer = False

        messages: list[BaseMessage] = [AIMessage(content="...")]

        result = await mixin._handle_goal_continuation(
            collected_messages=messages,
            tools_called_this_turn=True,
            net_tokens_this_turn=1000,
            cost_this_turn=0.05,
            time_this_turn_seconds=10,
        )

        assert result is False
        callback.assert_not_called()
