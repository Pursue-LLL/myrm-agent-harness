from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.goals.audit import build_wrapup_prompt
from myrm_agent_harness.agent.goals.continuation import (
    _WRAPUP_SENTINEL,
    _extract_last_ai_response,
    _judge_completion,
    _make_tamper_decision,
    _run_acceptance_verification,
    _wrapup_already_injected,
    check_continuation,
)
from myrm_agent_harness.agent.goals.invariant_snapshot import ProtectedFileViolation
from myrm_agent_harness.agent.goals.types import ContinuationDecision, Goal, GoalBudget, GoalStatus
from myrm_agent_harness.agent.goals.verification.base import AggregatedVerificationResult, VerificationResult


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
    provider.record_progress.return_value = goal
    provider.record_loop_restart.return_value = goal
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
        cost_this_turn=0.0,
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
        cost_this_turn=0.0,
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
        cost_this_turn=0.0,
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
        cost_this_turn=0.0,
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
        cost_this_turn=0.0,
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
        cost_this_turn=0.0,
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
    mock_goal_provider.record_progress.return_value = goal

    # First call: wrap-up turn granted (collected_messages is empty, no prior wrap-up)
    collected_messages: list = []
    decision = await check_continuation(
        goal_provider=mock_goal_provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=collected_messages,
        tools_called_this_turn=True,
        net_tokens_this_turn=10,
        cost_this_turn=0.0,
        time_this_turn_seconds=1,
    )
    assert decision.should_continue is True
    assert decision.verdict == "continue"
    assert "wrap-up" in decision.reason.lower()

    # Second call: wrap-up already injected → truly stop
    decision2 = await check_continuation(
        goal_provider=mock_goal_provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=collected_messages,
        tools_called_this_turn=True,
        net_tokens_this_turn=10,
        cost_this_turn=0.0,
        time_this_turn_seconds=1,
    )
    assert decision2.should_continue is False
    assert decision2.verdict == "budget"


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
        cost_this_turn=0.0,
        time_this_turn_seconds=1,
    )

    assert decision.should_continue is True
    assert decision.verdict == "continue"
    mock_goal_provider.account_usage.assert_awaited_once_with(
        "test-goal", token_delta=10, cost_delta=0.0, time_delta_seconds=1, turn_delta=1,
    )  # cost_delta=0.0 because cost_this_turn was passed as 0.0 in this test
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
    reason, parse_failed = await _judge_completion(provider, goal, "   ")
    assert reason == ""
    assert parse_failed is False
    provider.evaluate_semantic.assert_not_called()


@pytest.mark.asyncio
async def test_judge_completion_passed():
    provider = AsyncMock()
    provider.evaluate_semantic.return_value = VerificationResult(passed=True, reason="done")
    goal = Goal(goal_id="g1", session_id="s1", objective="obj", status=GoalStatus.ACTIVE)
    reason, parse_failed = await _judge_completion(provider, goal, "Task is complete.")
    assert reason is None
    assert parse_failed is False


@pytest.mark.asyncio
async def test_judge_completion_not_passed():
    provider = AsyncMock()
    provider.evaluate_semantic.return_value = VerificationResult(passed=False, reason="still working")
    goal = Goal(goal_id="g1", session_id="s1", objective="obj", status=GoalStatus.ACTIVE)
    reason, parse_failed = await _judge_completion(provider, goal, "Still working on it.")
    assert reason == "still working"
    assert parse_failed is False


@pytest.mark.asyncio
async def test_judge_completion_parse_failed():
    provider = AsyncMock()
    provider.evaluate_semantic.return_value = VerificationResult(
        passed=False, reason="garbage text", parse_failed=True
    )
    goal = Goal(goal_id="g1", session_id="s1", objective="obj", status=GoalStatus.ACTIVE)
    reason, parse_failed = await _judge_completion(provider, goal, "Still working on it.")
    assert reason == "garbage text"
    assert parse_failed is True


@pytest.mark.asyncio
async def test_judge_completion_not_implemented():
    provider = AsyncMock()
    provider.evaluate_semantic.side_effect = NotImplementedError
    goal = Goal(goal_id="g1", session_id="s1", objective="obj", status=GoalStatus.ACTIVE)
    reason, parse_failed = await _judge_completion(provider, goal, "Some response")
    assert reason == ""
    assert parse_failed is False


@pytest.mark.asyncio
async def test_judge_completion_error_failopen():
    provider = AsyncMock()
    provider.evaluate_semantic.side_effect = RuntimeError("API down")
    goal = Goal(goal_id="g1", session_id="s1", objective="obj", status=GoalStatus.ACTIVE)
    reason, parse_failed = await _judge_completion(provider, goal, "Some response")
    assert reason == ""
    assert parse_failed is False


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
    provider.record_progress.return_value = goal

    messages = [AIMessage(content="I have completed the task successfully.")]

    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=messages,
        tools_called_this_turn=True,
        net_tokens_this_turn=10,
        cost_this_turn=0.0,
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
    provider.record_progress.return_value = goal

    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=True,
        net_tokens_this_turn=10,
        cost_this_turn=0.0,
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
    provider.record_progress.return_value = goal

    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=True,
        net_tokens_this_turn=10,
        cost_this_turn=0.0,
        time_this_turn_seconds=1,
    )

    assert decision.should_continue is True
    assert decision.turns_used == 5
    assert decision.max_turns == 25
    assert decision.message != ""


# --- Convergence detection tests ---

@pytest.mark.asyncio
async def test_convergence_completes_goal():
    """When no_progress_streak >= convergence_window, goal should COMPLETE."""
    provider = AsyncMock()
    goal = Goal(
        goal_id="conv-goal",
        session_id="s1",
        objective="Find all bugs",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_turns=20, convergence_window=3),
        turns_used=8,
        no_progress_streak=2,
    )
    converged_goal = Goal(
        goal_id="conv-goal",
        session_id="s1",
        objective="Find all bugs",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_turns=20, convergence_window=3),
        turns_used=8,
        no_progress_streak=3,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = goal
    provider.is_continuation_suppressed.return_value = True
    provider.record_progress.return_value = converged_goal

    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=False,
        net_tokens_this_turn=10,
        cost_this_turn=0.0,
        time_this_turn_seconds=1,
    )

    assert decision.should_continue is False
    assert decision.verdict == "convergence"
    assert "convergence" in decision.reason.lower()
    provider.update_status.assert_called_once_with("conv-goal", GoalStatus.COMPLETE)


@pytest.mark.asyncio
async def test_convergence_not_reached_yet():
    """When no_progress_streak < convergence_window, standard suppression fires."""
    provider = AsyncMock()
    goal = Goal(
        goal_id="conv-goal",
        session_id="s1",
        objective="Find all bugs",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_turns=20, convergence_window=3),
        turns_used=8,
        no_progress_streak=0,
    )
    progress_goal = Goal(
        goal_id="conv-goal",
        session_id="s1",
        objective="Find all bugs",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_turns=20, convergence_window=3),
        turns_used=8,
        no_progress_streak=1,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = goal
    provider.is_continuation_suppressed.return_value = True
    provider.record_progress.return_value = progress_goal

    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=False,
        net_tokens_this_turn=10,
        cost_this_turn=0.0,
        time_this_turn_seconds=1,
    )

    assert decision.should_continue is False
    assert decision.verdict == "suppressed"


# --- Loop restart tests ---

@pytest.mark.asyncio
async def test_loop_restart_triggers():
    """When loop_on_pause=True and under max_restarts, verdict is loop_restart."""
    provider = AsyncMock()
    goal = Goal(
        goal_id="loop-goal",
        session_id="s1",
        objective="Run tests until failure",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_turns=20, loop_on_pause=True, max_loop_restarts=5),
        turns_used=4,
        loop_restarts=0,
    )
    restarted_goal = Goal(
        goal_id="loop-goal",
        session_id="s1",
        objective="Run tests until failure",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_turns=20, loop_on_pause=True, max_loop_restarts=5),
        turns_used=4,
        loop_restarts=1,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = goal
    provider.is_continuation_suppressed.return_value = True
    provider.record_progress.return_value = goal
    provider.record_loop_restart.return_value = restarted_goal

    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=False,
        net_tokens_this_turn=10,
        cost_this_turn=0.0,
        time_this_turn_seconds=1,
    )

    assert decision.should_continue is False
    assert decision.verdict == "loop_restart"
    provider.record_loop_restart.assert_called_once_with("loop-goal")


@pytest.mark.asyncio
async def test_loop_restart_exhausted_falls_to_suppressed():
    """When loop_restarts >= max_loop_restarts, falls to standard suppression."""
    provider = AsyncMock()
    goal = Goal(
        goal_id="loop-goal",
        session_id="s1",
        objective="Run tests",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_turns=20, loop_on_pause=True, max_loop_restarts=3),
        turns_used=10,
        loop_restarts=3,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = goal
    provider.is_continuation_suppressed.return_value = True
    provider.record_progress.return_value = goal

    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=False,
        net_tokens_this_turn=10,
        cost_this_turn=0.0,
        time_this_turn_seconds=1,
    )

    assert decision.should_continue is False
    assert decision.verdict == "suppressed"
    provider.update_status.assert_called_once_with("loop-goal", GoalStatus.PAUSED)


@pytest.mark.asyncio
async def test_convergence_takes_priority_over_loop_restart():
    """When both convergence and loop_on_pause are set, convergence wins."""
    provider = AsyncMock()
    goal = Goal(
        goal_id="both-goal",
        session_id="s1",
        objective="Find all bugs",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(
            max_turns=20,
            convergence_window=2,
            loop_on_pause=True,
            max_loop_restarts=5,
        ),
        turns_used=8,
        no_progress_streak=1,
    )
    converged_goal = Goal(
        goal_id="both-goal",
        session_id="s1",
        objective="Find all bugs",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(
            max_turns=20,
            convergence_window=2,
            loop_on_pause=True,
            max_loop_restarts=5,
        ),
        turns_used=8,
        no_progress_streak=2,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = goal
    provider.is_continuation_suppressed.return_value = True
    provider.record_progress.return_value = converged_goal

    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=False,
        net_tokens_this_turn=10,
        cost_this_turn=0.0,
        time_this_turn_seconds=1,
    )

    assert decision.verdict == "convergence"
    provider.update_status.assert_called_once_with("both-goal", GoalStatus.COMPLETE)


# --- _wrapup_already_injected tests ---

def test_wrapup_already_injected_empty_messages():
    assert _wrapup_already_injected([]) is False


def test_wrapup_already_injected_no_human_messages():
    messages = [AIMessage(content="Hello")]
    assert _wrapup_already_injected(messages) is False


def test_wrapup_already_injected_with_sentinel():
    messages = [
        HumanMessage(content="user msg"),
        AIMessage(content="response"),
        HumanMessage(content=f"{_WRAPUP_SENTINEL}\n\nobjective..."),
    ]
    assert _wrapup_already_injected(messages) is True


def test_wrapup_already_injected_without_sentinel():
    messages = [
        HumanMessage(content="user msg"),
        AIMessage(content="response"),
        HumanMessage(content="[Continuing toward your standing goal]"),
    ]
    assert _wrapup_already_injected(messages) is False


def test_wrapup_already_injected_sentinel_only_checks_last_human():
    messages = [
        HumanMessage(content=f"{_WRAPUP_SENTINEL}\n\nobjective..."),
        AIMessage(content="wrap-up response"),
        HumanMessage(content="user follow-up"),
    ]
    # Last HumanMessage is "user follow-up", not the sentinel
    assert _wrapup_already_injected(messages) is False


# --- build_wrapup_prompt tests ---

def test_build_wrapup_prompt_basic():
    goal = Goal(
        goal_id="g1",
        session_id="s1",
        objective="Refactor the auth module",
        status=GoalStatus.BUDGET_LIMITED,
        time_used_seconds=120,
    )
    prompt = build_wrapup_prompt(goal)
    assert prompt.startswith(_WRAPUP_SENTINEL)
    assert "<untrusted_objective>" in prompt
    assert "Refactor the auth module" in prompt
    assert "120s" in prompt
    assert "Do NOT call any tools" in prompt
    assert "Do NOT start any new substantive work" in prompt


def test_build_wrapup_prompt_with_all_budget_dimensions():
    goal = Goal(
        goal_id="g2",
        session_id="s1",
        objective="Write tests",
        status=GoalStatus.BUDGET_LIMITED,
        budget=GoalBudget(max_tokens=50000, max_usd=1.5, max_turns=10),
        tokens_used=48000,
        cost_usd=1.42,
        turns_used=10,
        time_used_seconds=300,
    )
    prompt = build_wrapup_prompt(goal)
    assert "48000 / 50000" in prompt
    assert "$1.4200 / $1.5000" in prompt
    assert "10 / 10" in prompt
    assert "300s" in prompt


def test_build_wrapup_prompt_with_partial_budget():
    goal = Goal(
        goal_id="g3",
        session_id="s1",
        objective="Deploy app",
        status=GoalStatus.BUDGET_LIMITED,
        budget=GoalBudget(max_turns=5),
        turns_used=5,
        time_used_seconds=60,
    )
    prompt = build_wrapup_prompt(goal)
    assert "5 / 5" in prompt
    assert "60s" in prompt
    # No tokens or usd lines since not set in budget
    assert "Tokens used:" not in prompt
    assert "Cost:" not in prompt


# --- Budget limited wrap-up with budget details ---

@pytest.mark.asyncio
async def test_budget_limited_wrapup_injects_budget_info():
    """Verify the wrap-up message contains budget details from the goal."""
    provider = AsyncMock()
    goal = Goal(
        goal_id="budget-goal",
        session_id="s1",
        objective="Long running task",
        status=GoalStatus.BUDGET_LIMITED,
        budget=GoalBudget(max_tokens=10000, max_turns=5),
        tokens_used=9500,
        turns_used=5,
        time_used_seconds=180,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = goal
    provider.record_progress.return_value = goal

    collected: list = []
    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=collected,
        tools_called_this_turn=True,
        net_tokens_this_turn=10,
        cost_this_turn=0.0,
        time_this_turn_seconds=1,
    )

    assert decision.should_continue is True
    assert decision.message is not None
    assert "9500 / 10000" in decision.message
    assert "5 / 5" in decision.message
    assert "180s" in decision.message
    assert len(collected) == 1
    assert isinstance(collected[0], HumanMessage)
    assert collected[0].name == "developer"


# --- Edge cases ---

def test_wrapup_already_injected_non_string_content():
    """HumanMessage with list content (multimodal) should not crash."""
    messages = [
        HumanMessage(content=[{"type": "text", "text": "image description"}]),
    ]
    assert _wrapup_already_injected(messages) is False


def test_build_wrapup_prompt_no_budget():
    """Goal with no budget set should still produce a valid prompt."""
    goal = Goal(
        goal_id="g-no-budget",
        session_id="s1",
        objective="Quick task",
        status=GoalStatus.BUDGET_LIMITED,
        time_used_seconds=30,
    )
    prompt = build_wrapup_prompt(goal)
    assert _WRAPUP_SENTINEL in prompt
    assert "Quick task" in prompt
    assert "30s" in prompt
    assert "Do NOT call any tools" in prompt


@pytest.mark.asyncio
async def test_budget_limited_cancelled_takes_priority():
    """Cancellation (step 3) fires before budget-limited (step 5)."""
    provider = AsyncMock()
    goal = Goal(
        goal_id="cancel-budget",
        session_id="s1",
        objective="Test",
        status=GoalStatus.BUDGET_LIMITED,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = goal
    provider.record_progress.return_value = goal

    cancel_token = MagicMock()
    cancel_token.is_cancelled = True

    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=cancel_token,
        steering_token=None,
        collected_messages=[],
        tools_called_this_turn=True,
        net_tokens_this_turn=10,
        cost_this_turn=0.0,
        time_this_turn_seconds=1,
    )
    assert decision.verdict == "cancelled"
    assert decision.should_continue is False


@pytest.mark.asyncio
async def test_budget_limited_steering_takes_priority():
    """Steering (step 4) fires before budget-limited (step 5)."""
    provider = AsyncMock()
    goal = Goal(
        goal_id="steer-budget",
        session_id="s1",
        objective="Test",
        status=GoalStatus.BUDGET_LIMITED,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = goal
    provider.record_progress.return_value = goal

    steering_token = MagicMock()
    steering_token.has_pending = True

    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=None,
        steering_token=steering_token,
        collected_messages=[],
        tools_called_this_turn=True,
        net_tokens_this_turn=10,
        cost_this_turn=0.0,
        time_this_turn_seconds=1,
    )
    assert decision.verdict == "steering"
    assert decision.should_continue is False


# --- Judge parse failure auto-pause tests ---

@pytest.mark.asyncio
async def test_judge_parse_failure_increments_counter():
    """Parse failure increments consecutive_judge_parse_failures but continues."""
    from myrm_agent_harness.agent.goals.continuation import _MAX_CONSECUTIVE_JUDGE_PARSE_FAILURES

    provider = AsyncMock()
    goal = Goal(
        goal_id="parse-goal",
        session_id="s1",
        objective="Test parse failure",
        status=GoalStatus.ACTIVE,
        turns_used=3,
        consecutive_judge_parse_failures=0,
    )
    goal_after_record = Goal(
        goal_id="parse-goal",
        session_id="s1",
        objective="Test parse failure",
        status=GoalStatus.ACTIVE,
        turns_used=3,
        consecutive_judge_parse_failures=1,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = goal
    provider.is_continuation_suppressed.return_value = False
    provider.record_progress.return_value = goal
    provider.evaluate_semantic.return_value = VerificationResult(
        passed=False, reason="unparseable garbage", parse_failed=True
    )
    provider.record_judge_parse_result.return_value = goal_after_record

    messages = [AIMessage(content="I did some work with tools.")]
    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=messages,
        tools_called_this_turn=True,
        net_tokens_this_turn=100,
        cost_this_turn=0.01,
        time_this_turn_seconds=5,
    )

    assert decision.should_continue is True
    assert decision.verdict == "continue"
    provider.record_judge_parse_result.assert_called_once_with("parse-goal", parse_failed=True)


@pytest.mark.asyncio
async def test_judge_parse_failure_auto_pause_at_threshold():
    """Three consecutive parse failures triggers auto-pause."""
    from myrm_agent_harness.agent.goals.continuation import _MAX_CONSECUTIVE_JUDGE_PARSE_FAILURES

    provider = AsyncMock()
    goal = Goal(
        goal_id="parse-goal",
        session_id="s1",
        objective="Test parse failure",
        status=GoalStatus.ACTIVE,
        turns_used=5,
        consecutive_judge_parse_failures=2,
    )
    goal_at_threshold = Goal(
        goal_id="parse-goal",
        session_id="s1",
        objective="Test parse failure",
        status=GoalStatus.ACTIVE,
        turns_used=5,
        consecutive_judge_parse_failures=3,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = goal
    provider.is_continuation_suppressed.return_value = False
    provider.record_progress.return_value = goal
    provider.evaluate_semantic.return_value = VerificationResult(
        passed=False, reason="still garbage", parse_failed=True
    )
    provider.record_judge_parse_result.return_value = goal_at_threshold

    messages = [AIMessage(content="I did some work.")]
    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=messages,
        tools_called_this_turn=True,
        net_tokens_this_turn=100,
        cost_this_turn=0.01,
        time_this_turn_seconds=5,
    )

    assert decision.should_continue is False
    assert decision.verdict == "suppressed"
    assert "unparseable output" in decision.reason
    assert str(_MAX_CONSECUTIVE_JUDGE_PARSE_FAILURES) in decision.reason
    provider.update_status.assert_called_once_with("parse-goal", GoalStatus.PAUSED)


@pytest.mark.asyncio
async def test_judge_parse_success_resets_counter():
    """Successful parse resets consecutive_judge_parse_failures to 0."""
    provider = AsyncMock()
    goal = Goal(
        goal_id="parse-goal",
        session_id="s1",
        objective="Test parse reset",
        status=GoalStatus.ACTIVE,
        turns_used=4,
        consecutive_judge_parse_failures=2,
    )
    goal_after_reset = Goal(
        goal_id="parse-goal",
        session_id="s1",
        objective="Test parse reset",
        status=GoalStatus.ACTIVE,
        turns_used=4,
        consecutive_judge_parse_failures=0,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = goal
    provider.is_continuation_suppressed.return_value = False
    provider.record_progress.return_value = goal
    provider.evaluate_semantic.return_value = VerificationResult(
        passed=False, reason="not done yet", parse_failed=False
    )
    provider.record_judge_parse_result.return_value = goal_after_reset

    messages = [AIMessage(content="Working on it.")]
    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=messages,
        tools_called_this_turn=True,
        net_tokens_this_turn=100,
        cost_this_turn=0.01,
        time_this_turn_seconds=5,
    )

    assert decision.should_continue is True
    assert decision.verdict == "continue"
    provider.record_judge_parse_result.assert_called_once_with("parse-goal", parse_failed=False)


@pytest.mark.asyncio
async def test_judge_parse_success_skips_db_when_counter_zero():
    """When counter is already 0, successful parse skips the DB call."""
    provider = AsyncMock()
    goal = Goal(
        goal_id="zero-counter-goal",
        session_id="s1",
        objective="Test zero counter optimization",
        status=GoalStatus.ACTIVE,
        turns_used=4,
        consecutive_judge_parse_failures=0,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = goal
    provider.is_continuation_suppressed.return_value = False
    provider.record_progress.return_value = goal
    provider.evaluate_semantic.return_value = VerificationResult(
        passed=False, reason="not done yet", parse_failed=False
    )

    messages = [AIMessage(content="Working on it.")]
    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=messages,
        tools_called_this_turn=True,
        net_tokens_this_turn=100,
        cost_this_turn=0.01,
        time_this_turn_seconds=5,
    )

    assert decision.should_continue is True
    assert decision.verdict == "continue"
    provider.record_judge_parse_result.assert_not_called()


@pytest.mark.asyncio
async def test_judge_api_error_does_not_count_as_parse_failure():
    """API/transport errors should not increment parse failures; they reset the counter."""
    provider = AsyncMock()
    goal = Goal(
        goal_id="api-err-goal",
        session_id="s1",
        objective="Test API error",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_turns=20),
        turns_used=3,
        consecutive_judge_parse_failures=2,
    )
    goal_after_reset = Goal(
        goal_id="api-err-goal",
        session_id="s1",
        objective="Test API error",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_turns=20),
        turns_used=3,
        consecutive_judge_parse_failures=0,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = goal
    provider.is_continuation_suppressed.return_value = False
    provider.record_progress.return_value = goal
    provider.evaluate_semantic.side_effect = RuntimeError("Connection timeout")
    provider.record_judge_parse_result.return_value = goal_after_reset

    messages = [AIMessage(content="Some work done.")]
    decision = await check_continuation(
        goal_provider=provider,
        session_id="s1",
        cancel_token=None,
        steering_token=None,
        collected_messages=messages,
        tools_called_this_turn=True,
        net_tokens_this_turn=100,
        cost_this_turn=0.01,
        time_this_turn_seconds=5,
    )

    assert decision.should_continue is True
    assert decision.verdict == "continue"
    # API error → _judge_completion returns ("", False) → parse_failed=False
    # Since goal had consecutive_judge_parse_failures=2 > 0, the counter is RESET
    # (not incremented). This prevents flaky networks from tripping the auto-pause.
    provider.record_judge_parse_result.assert_called_once_with("api-err-goal", parse_failed=False)


# ---------------------------------------------------------------------------
# _run_acceptance_verification tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acceptance_verification_no_criteria():
    """No acceptance_criteria → skip verification, return True."""
    provider = AsyncMock()
    goal = Goal(goal_id="g1", session_id="s1", objective="o", status=GoalStatus.ACTIVE)
    assert await _run_acceptance_verification(provider, goal) is True
    provider.increment_verification_retries.assert_not_called()


@pytest.mark.asyncio
async def test_acceptance_verification_pass():
    """All criteria pass → return True without incrementing retries."""
    provider = AsyncMock()
    goal = Goal(
        goal_id="g1", session_id="s1", objective="o",
        status=GoalStatus.ACTIVE,
        acceptance_criteria=[{"type": "shell", "command": "echo ok"}],
    )
    mock_gk = MagicMock()
    mock_gk.verify_all = AsyncMock(return_value=AggregatedVerificationResult(passed=True, per_criterion=[
        VerificationResult(passed=True, criterion_label="echo ok"),
    ]))
    with patch(
        "myrm_agent_harness.agent.goals.verification.gatekeeper.VerificationGatekeeper",
        return_value=mock_gk,
    ):
        assert await _run_acceptance_verification(provider, goal) is True
    provider.record_acceptance_results.assert_called_once()
    provider.increment_verification_retries.assert_not_called()


@pytest.mark.asyncio
async def test_acceptance_verification_fail_increments_retries():
    """Verification failure → increment retries, return False."""
    provider = AsyncMock()
    updated_goal = Goal(
        goal_id="g1", session_id="s1", objective="o",
        status=GoalStatus.ACTIVE, verification_retries=1,
    )
    provider.increment_verification_retries.return_value = updated_goal

    goal = Goal(
        goal_id="g1", session_id="s1", objective="o",
        status=GoalStatus.ACTIVE,
        acceptance_criteria=[{"type": "shell", "command": "false"}],
    )
    mock_gk = MagicMock()
    mock_gk.verify_all = AsyncMock(return_value=AggregatedVerificationResult(passed=False, per_criterion=[
        VerificationResult(passed=False, criterion_label="false", reason="cmd failed"),
    ]))
    with patch(
        "myrm_agent_harness.agent.goals.verification.gatekeeper.VerificationGatekeeper",
        return_value=mock_gk,
    ):
        assert await _run_acceptance_verification(provider, goal) is False
    provider.record_acceptance_results.assert_called_once()
    provider.increment_verification_retries.assert_called_once_with("g1")
    provider.update_status.assert_not_called()


@pytest.mark.asyncio
async def test_acceptance_verification_fail_fuse_pauses():
    """Verification failure exceeding threshold → PAUSE the goal."""
    provider = AsyncMock()
    updated_goal = Goal(
        goal_id="g1", session_id="s1", objective="o",
        status=GoalStatus.ACTIVE, verification_retries=3,
    )
    provider.increment_verification_retries.return_value = updated_goal

    goal = Goal(
        goal_id="g1", session_id="s1", objective="o",
        status=GoalStatus.ACTIVE,
        acceptance_criteria=[{"type": "shell", "command": "false"}],
    )
    mock_gk = MagicMock()
    mock_gk.verify_all = AsyncMock(return_value=AggregatedVerificationResult(passed=False, per_criterion=[
        VerificationResult(passed=False, criterion_label="false", reason="still failing"),
    ]))
    with patch(
        "myrm_agent_harness.agent.goals.verification.gatekeeper.VerificationGatekeeper",
        return_value=mock_gk,
    ):
        assert await _run_acceptance_verification(provider, goal) is False
    provider.record_acceptance_results.assert_called_once()
    provider.update_status.assert_called_once_with("g1", GoalStatus.PAUSED)


@pytest.mark.asyncio
async def test_acceptance_verification_crash_increments_retries():
    """Gatekeeper construction crash → increment retries (not silently ignore)."""
    provider = AsyncMock()
    updated_goal = Goal(
        goal_id="g1", session_id="s1", objective="o",
        status=GoalStatus.ACTIVE, verification_retries=1,
    )
    provider.increment_verification_retries.return_value = updated_goal

    goal = Goal(
        goal_id="g1", session_id="s1", objective="o",
        status=GoalStatus.ACTIVE,
        acceptance_criteria=[{"type": "shell"}],
    )
    with patch(
        "myrm_agent_harness.agent.goals.verification.gatekeeper.VerificationGatekeeper",
        side_effect=KeyError("command"),
    ):
        assert await _run_acceptance_verification(provider, goal) is False
    provider.increment_verification_retries.assert_called_once_with("g1")
    provider.update_status.assert_not_called()


@pytest.mark.asyncio
async def test_acceptance_verification_crash_fuse_pauses():
    """Gatekeeper crash exceeding threshold → PAUSE the goal (fuse protection)."""
    provider = AsyncMock()
    updated_goal = Goal(
        goal_id="g1", session_id="s1", objective="o",
        status=GoalStatus.ACTIVE, verification_retries=3,
    )
    provider.increment_verification_retries.return_value = updated_goal

    goal = Goal(
        goal_id="g1", session_id="s1", objective="o",
        status=GoalStatus.ACTIVE,
        acceptance_criteria=[{"type": "shell"}],
    )
    with patch(
        "myrm_agent_harness.agent.goals.verification.gatekeeper.VerificationGatekeeper",
        side_effect=TypeError("bad config"),
    ):
        assert await _run_acceptance_verification(provider, goal) is False
    provider.increment_verification_retries.assert_called_once_with("g1")
    provider.update_status.assert_called_once_with("g1", GoalStatus.PAUSED)


# ── Protected file tamper detection ──────────────────────────────────────


def test_make_tamper_decision_builds_continue():
    """_make_tamper_decision returns a continue decision with violation details."""
    goal = Goal(
        goal_id="g1", session_id="s1", objective="o",
        status=GoalStatus.ACTIVE, turns_used=5,
        budget=GoalBudget(max_turns=10),
    )
    violations = [
        ProtectedFileViolation(path="tests/a.py", pattern="tests/**", kind="modified"),
        ProtectedFileViolation(path="tests/b.py", pattern="tests/**", kind="deleted"),
    ]
    decision = _make_tamper_decision(goal, violations)
    assert decision.should_continue is True
    assert decision.verdict == "continue"
    assert "BLOCKED" in decision.message
    assert "tests/a.py (modified)" in decision.message
    assert "tests/b.py (deleted)" in decision.message
    assert decision.turns_used == 5
    assert decision.max_turns == 10


@pytest.mark.asyncio
async def test_convergence_blocked_by_tamper():
    """Convergence path must block when protected files are tampered."""
    provider = AsyncMock()
    goal = Goal(
        goal_id="conv-tamper",
        session_id="s1",
        objective="Find bugs",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_turns=20, convergence_window=3),
        turns_used=8,
        no_progress_streak=2,
    )
    converged_goal = Goal(
        goal_id="conv-tamper",
        session_id="s1",
        objective="Find bugs",
        status=GoalStatus.ACTIVE,
        budget=GoalBudget(max_turns=20, convergence_window=3),
        turns_used=8,
        no_progress_streak=3,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = goal
    provider.is_continuation_suppressed.return_value = True
    provider.record_progress.return_value = converged_goal

    fake_violations = [ProtectedFileViolation(path="tests/x.py", pattern="tests/**", kind="modified")]
    with patch(
        "myrm_agent_harness.agent.goals.continuation._check_protected_integrity",
        return_value=fake_violations,
    ):
        decision = await check_continuation(
            goal_provider=provider,
            session_id="s1",
            cancel_token=None,
            steering_token=None,
            collected_messages=[],
            tools_called_this_turn=False,
            net_tokens_this_turn=10,
            cost_this_turn=0.0,
            time_this_turn_seconds=1,
        )

    assert decision.should_continue is True
    assert decision.verdict == "continue"
    assert "BLOCKED" in decision.message
    provider.update_status.assert_not_called()
    provider.reset_suppression.assert_called_once_with("s1")


@pytest.mark.asyncio
async def test_semantic_judge_blocked_by_tamper():
    """Semantic judge completion path must block when protected files are tampered."""
    provider = AsyncMock()
    goal = Goal(
        goal_id="judge-tamper",
        session_id="s1",
        objective="Fix the issue",
        status=GoalStatus.ACTIVE,
        tokens_used=100,
        turns_used=3,
    )
    provider.get_active_goal.return_value = goal
    provider.get_goal.return_value = goal
    provider.is_continuation_suppressed.return_value = False
    provider.evaluate_semantic.return_value = VerificationResult(passed=True, reason="done")
    provider.record_progress.return_value = goal

    messages = [AIMessage(content="I have completed the task.")]
    fake_violations = [ProtectedFileViolation(path="src/main.py", pattern="src/**", kind="deleted")]
    with patch(
        "myrm_agent_harness.agent.goals.continuation._check_protected_integrity",
        return_value=fake_violations,
    ):
        decision = await check_continuation(
            goal_provider=provider,
            session_id="s1",
            cancel_token=None,
            steering_token=None,
            collected_messages=messages,
            tools_called_this_turn=True,
            net_tokens_this_turn=10,
            cost_this_turn=0.0,
            time_this_turn_seconds=1,
        )

    assert decision.should_continue is True
    assert decision.verdict == "continue"
    assert "BLOCKED" in decision.message
    assert "src/main.py (deleted)" in decision.message
    provider.update_status.assert_not_called()
