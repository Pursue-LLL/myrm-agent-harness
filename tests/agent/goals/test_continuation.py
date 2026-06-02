from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.goals.continuation import (
    _extract_last_ai_response,
    _judge_completion,
    check_continuation,
)
from myrm_agent_harness.agent.goals.types import ContinuationDecision, Goal, GoalBudget, GoalStatus
from myrm_agent_harness.agent.goals.verification.base import VerificationResult


@pytest.fixture
def mock_goal_provider():
    provider = AsyncMock()
    goal = Goal(
        goal_id="test-goal",
        session_id="test-session",
        objective="Test objective",
        status=GoalStatus.ACTIVE,
        tokens_used=100,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = goal
    provider.is_continuation_suppressed.return_value = False
    return provider


@pytest.mark.asyncio
async def test_check_continuation_no_provider():
    decision = await check_continuation(
        goal_provider=None,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=True,
        net_tokens_this_turn=10,
        time_this_turn_seconds=1,
    )
    assert isinstance(decision, ContinuationDecision)
    assert decision.should_continue is False
    assert decision.verdict == "no_goal"


@pytest.mark.asyncio
async def test_check_continuation_no_active_goal(mock_goal_provider):
    mock_goal_provider.get_active_goal.return_value = None

    decision = await check_continuation(
        goal_provider=mock_goal_provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=True,
        net_tokens_this_turn=10,
        time_this_turn_seconds=1,
    )
    assert decision.should_continue is False
    assert decision.verdict == "no_goal"


@pytest.mark.asyncio
async def test_check_continuation_cancelled(mock_goal_provider):
    cancel_token = MagicMock()
    cancel_token.is_cancelled = True

    decision = await check_continuation(
        goal_provider=mock_goal_provider,
        session_id="s1",
        cancel_token=cancel_token,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=True,
        net_tokens_this_turn=10,
        time_this_turn_seconds=1,
    )
    assert decision.should_continue is False
    assert decision.verdict == "cancelled"
    mock_goal_provider.update_status.assert_called_once_with("test-goal", GoalStatus.PAUSED)


@pytest.mark.asyncio
async def test_check_continuation_steering_pending(mock_goal_provider):
    steering_token = MagicMock()
    steering_token.has_pending = True

    decision = await check_continuation(
        goal_provider=mock_goal_provider,
        session_id="s1",
        cancel_token=None,
        steering_token=steering_token,
        collected_messages=[],
        tools_called_this_turn=True,
        net_tokens_this_turn=10,
        time_this_turn_seconds=1,
    )
    assert decision.should_continue is False
    assert decision.verdict == "steering"
    mock_goal_provider.update_status.assert_not_called()


@pytest.mark.asyncio
async def test_check_continuation_suppressed(mock_goal_provider):
    mock_goal_provider.is_continuation_suppressed.return_value = True

    decision = await check_continuation(
        goal_provider=mock_goal_provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=True,
        net_tokens_this_turn=10,
        time_this_turn_seconds=1,
    )
    assert decision.should_continue is False
    assert decision.verdict == "suppressed"
    mock_goal_provider.update_status.assert_called_once_with("test-goal", GoalStatus.PAUSED)
    mock_goal_provider.reset_suppression.assert_called_once_with("s1")


@pytest.mark.asyncio
async def test_check_continuation_zero_tools_suppresses(mock_goal_provider):
    mock_goal_provider.is_continuation_suppressed.return_value = True

    decision = await check_continuation(
        goal_provider=mock_goal_provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=False,
        net_tokens_this_turn=10,
        time_this_turn_seconds=1,
    )

    mock_goal_provider.suppress_continuation.assert_called_once_with("s1")
    assert decision.should_continue is False
    assert decision.verdict == "suppressed"


@pytest.mark.asyncio
async def test_check_continuation_budget_limited(mock_goal_provider):
    goal = Goal(
        goal_id="test-goal",
        session_id="test-session",
        objective="Test objective",
        status=GoalStatus.BUDGET_LIMITED,
    )
    mock_goal_provider.get_goal.return_value = goal

    decision = await check_continuation(
        goal_provider=mock_goal_provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=True,
        net_tokens_this_turn=10,
        time_this_turn_seconds=1,
    )
    assert decision.should_continue is False
    assert decision.verdict == "budget"


@pytest.mark.asyncio
async def test_check_continuation_success(mock_goal_provider):
    collected_messages: list = []

    mock_goal_provider.is_continuation_suppressed.return_value = False

    decision = await check_continuation(
        goal_provider=mock_goal_provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=collected_messages,
        tools_called_this_turn=True,
        net_tokens_this_turn=10,
        time_this_turn_seconds=1,
    )

    assert decision.should_continue is True
    assert decision.verdict == "continue"
    mock_goal_provider.account_usage.assert_awaited_once_with(
        "test-goal", token_delta=10, cost_delta=0.0, time_delta_seconds=1, turn_delta=1,
    )
    assert len(collected_messages) == 1
    assert isinstance(collected_messages[0], HumanMessage)
    assert collected_messages[0].name == "developer"
    assert "Test objective" in collected_messages[0].content
    mock_goal_provider.reset_suppression.assert_called_once_with("s1")


# --- _extract_last_ai_response tests ---

def test_extract_last_ai_response_str_content():
    messages = [AIMessage(content="Hello world")]
    assert _extract_last_ai_response(messages) == "Hello world"


def test_extract_last_ai_response_list_content():
    messages = [
        AIMessage(content=[
            {"type": "thinking", "text": "should be skipped"},
            {"type": "text", "text": "visible text"},
            "raw string part",
        ])
    ]
    result = _extract_last_ai_response(messages)
    assert "visible text" in result
    assert "raw string part" in result
    assert "should be skipped" not in result


def test_extract_last_ai_response_empty():
    messages = [HumanMessage(content="only human")]
    assert _extract_last_ai_response(messages) == ""


def test_extract_last_ai_response_no_messages():
    assert _extract_last_ai_response([]) == ""


# --- _judge_completion tests ---

@pytest.mark.asyncio
async def test_judge_completion_empty_response():
    provider = AsyncMock()
    goal = Goal(goal_id="g1", session_id="s1", objective="obj", status=GoalStatus.ACTIVE)
    result = await _judge_completion(provider, goal, "   ")
    assert result is False
    provider.evaluate_semantic.assert_not_called()


@pytest.mark.asyncio
async def test_judge_completion_passed():
    provider = AsyncMock()
    provider.evaluate_semantic.return_value = VerificationResult(passed=True, reason="done")
    goal = Goal(goal_id="g1", session_id="s1", objective="obj", status=GoalStatus.ACTIVE)
    result = await _judge_completion(provider, goal, "Task is complete.")
    assert result is True


@pytest.mark.asyncio
async def test_judge_completion_not_passed():
    provider = AsyncMock()
    provider.evaluate_semantic.return_value = VerificationResult(passed=False, reason="still working")
    goal = Goal(goal_id="g1", session_id="s1", objective="obj", status=GoalStatus.ACTIVE)
    result = await _judge_completion(provider, goal, "Still working on it.")
    assert result is False


@pytest.mark.asyncio
async def test_judge_completion_not_implemented():
    provider = AsyncMock()
    provider.evaluate_semantic.side_effect = NotImplementedError
    goal = Goal(goal_id="g1", session_id="s1", objective="obj", status=GoalStatus.ACTIVE)
    result = await _judge_completion(provider, goal, "Some response")
    assert result is False


@pytest.mark.asyncio
async def test_judge_completion_error_failopen():
    provider = AsyncMock()
    provider.evaluate_semantic.side_effect = RuntimeError("API down")
    goal = Goal(goal_id="g1", session_id="s1", objective="obj", status=GoalStatus.ACTIVE)
    result = await _judge_completion(provider, goal, "Some response")
    assert result is False


# --- Semantic judge integration in check_continuation ---

@pytest.mark.asyncio
async def test_check_continuation_semantic_judge_completes():
    provider = AsyncMock()
    goal = Goal(
        goal_id="test-goal",
        session_id="test-session",
        objective="Test objective",
        status=GoalStatus.ACTIVE,
        tokens_used=100,
        turns_used=3,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = goal
    provider.is_continuation_suppressed.return_value = False
    provider.evaluate_semantic.return_value = VerificationResult(passed=True, reason="goal done")

    messages = [AIMessage(content="I have completed the task successfully.")]

    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=messages,
        tools_called_this_turn=True,
        net_tokens_this_turn=10,
        time_this_turn_seconds=1,
    )

    assert decision.should_continue is False
    assert decision.verdict == "done"
    provider.update_status.assert_called_once_with("test-goal", GoalStatus.COMPLETE)


@pytest.mark.asyncio
async def test_check_continuation_goal_disappears_after_accounting():
    provider = AsyncMock()
    goal = Goal(
        goal_id="test-goal",
        session_id="test-session",
        objective="Test objective",
        status=GoalStatus.ACTIVE,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = None

    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=True,
        net_tokens_this_turn=10,
        time_this_turn_seconds=1,
    )

    assert decision.should_continue is False
    assert decision.verdict == "no_goal"


@pytest.mark.asyncio
async def test_check_continuation_decision_has_turns_info():
    provider = AsyncMock()
    goal = Goal(
        goal_id="test-goal",
        session_id="test-session",
        objective="Test objective",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_turns=25),
        turns_used=5,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = goal
    provider.is_continuation_suppressed.return_value = False

    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=True,
        net_tokens_this_turn=10,
        time_this_turn_seconds=1,
    )

    assert decision.should_continue is True
    assert decision.turns_used == 5
    assert decision.max_turns == 25
    assert decision.message != ""
