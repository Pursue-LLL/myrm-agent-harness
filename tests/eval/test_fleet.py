"""Tests for Fleet Evaluation Runner, Variance Estimation & Resume Engine."""

from __future__ import annotations

import pytest
from myrm_agent_harness.eval import (
    AgentExecutor,
    AgentResponse,
    EvalCase,
    EvalResult,
    EvalTurnResult,
    FleetEvalResult,
    FleetEvalRunner,
    FleetVarianceMetrics,
    MultiTurnEvalCase,
    calculate_fleet_variance,
)


class MockExecutor(AgentExecutor):
    """Mock executor returning predictable responses."""

    def __init__(self, answer: str = "mock answer", pass_all: bool = True) -> None:
        self.answer = answer
        self.pass_all = pass_all
        self.call_count = 0

    async def execute(
        self,
        case: EvalCase,
        session_id: str | None = None,
    ) -> AgentResponse:
        self.call_count += 1
        return AgentResponse(
            answer=self.answer,
            tools_called=["tool_a"],
            token_usage={"total_tokens": 100},
            cost=0.001,
        )


def test_calculate_fleet_variance_empty() -> None:
    """Empty results should return default zeroed metrics."""
    metrics = calculate_fleet_variance([])
    assert metrics.n_attempts == 1
    assert metrics.mean_pass_rate == 0.0
    assert metrics.std_dev == 0.0
    assert metrics.pass_at_1 == 0.0


def test_calculate_fleet_variance_single_attempt() -> None:
    """Single attempt should have zero standard deviation."""
    turn = EvalTurnResult(
        case=EvalCase(message="task 1"),
        response=AgentResponse(answer="ok"),
        assertion_passed=True,
    )
    res = EvalResult(turn_results=[turn])
    metrics = calculate_fleet_variance([res])
    assert metrics.n_attempts == 1
    assert metrics.mean_pass_rate == 1.0
    assert metrics.std_dev == 0.0
    assert metrics.margin_of_error_95 == 0.0
    assert metrics.pass_at_1 == 1.0
    assert metrics.pass_at_k == 1.0


def test_calculate_fleet_variance_multiple_attempts() -> None:
    """Multiple attempts should compute sample standard deviation, pass@k, and difficulty breakdown."""
    cases = [
        MultiTurnEvalCase(
            turns=[EvalCase(message="easy task", metadata={"difficulty": "easy"})],
            metadata={"difficulty": "easy", "task_id": "T1"},
        ),
        MultiTurnEvalCase(
            turns=[EvalCase(message="hard task", metadata={"difficulty": "hard"})],
            metadata={"difficulty": "hard", "task_id": "T2"},
        ),
    ]

    # Attempt 1: T1 pass, T2 fail -> 50%
    r1 = EvalResult(
        turn_results=[
            EvalTurnResult(case=cases[0].turns[0], response=AgentResponse(answer=""), assertion_passed=True),
            EvalTurnResult(case=cases[1].turns[0], response=AgentResponse(answer=""), assertion_passed=False),
        ]
    )
    # Attempt 2: T1 pass, T2 pass -> 100%
    r2 = EvalResult(
        turn_results=[
            EvalTurnResult(case=cases[0].turns[0], response=AgentResponse(answer=""), assertion_passed=True),
            EvalTurnResult(case=cases[1].turns[0], response=AgentResponse(answer=""), assertion_passed=True),
        ]
    )
    # Attempt 3: T1 pass, T2 fail -> 50%
    r3 = EvalResult(
        turn_results=[
            EvalTurnResult(case=cases[0].turns[0], response=AgentResponse(answer=""), assertion_passed=True),
            EvalTurnResult(case=cases[1].turns[0], response=AgentResponse(answer=""), assertion_passed=False),
        ]
    )

    metrics = calculate_fleet_variance([r1, r2, r3], cases=cases)
    assert metrics.n_attempts == 3
    # Mean of (0.5, 1.0, 0.5) is ~0.6667
    assert pytest.approx(metrics.mean_pass_rate, 0.001) == 0.6667
    assert metrics.std_dev > 0
    # Both T1 and T2 were passed in at least one attempt (T2 in attempt 2) -> Pass@3 is 100%
    assert metrics.pass_at_k == 1.0
    assert "easy" in metrics.difficulty_breakdown
    assert metrics.difficulty_breakdown["easy"]["pass_rate"] == 1.0
    assert "hard" in metrics.difficulty_breakdown
    # Hard passed 1 of 3 times -> ~0.3333
    assert pytest.approx(metrics.difficulty_breakdown["hard"]["pass_rate"], 0.001) == 0.3333


@pytest.mark.asyncio
async def test_fleet_runner_multi_attempt_execution() -> None:
    """Fleet runner executes cases across n_attempts."""
    executor = MockExecutor()
    fleet_runner = FleetEvalRunner(executor, n_attempts=3, max_concurrency=2)

    cases = [
        MultiTurnEvalCase(turns=[EvalCase(message="task A", expected_tools=["tool_a"])]),
        MultiTurnEvalCase(turns=[EvalCase(message="task B", expected_tools=["tool_a"])]),
    ]

    fleet_result = await fleet_runner.run_multi_turn_fleet(cases)
    assert isinstance(fleet_result, FleetEvalResult)
    assert len(fleet_result.attempt_results) == 3
    assert fleet_result.variance_metrics.n_attempts == 3
    assert fleet_result.resumed_cases_count == 0
    assert "Fleet Eval (3 attempts)" in fleet_result.summary()
    assert "variance_metrics" in fleet_result.to_dict()


@pytest.mark.asyncio
async def test_fleet_runner_resume_skips_completed_cases() -> None:
    """Fleet runner reuses prior passed cases and executes only uncompleted ones."""
    executor = MockExecutor()
    fleet_runner = FleetEvalRunner(executor, n_attempts=2, max_concurrency=1)

    case_a = MultiTurnEvalCase(
        turns=[EvalCase(message="task A", expected_tools=["tool_a"])],
        metadata={"task_id": "T_A"},
    )
    case_b = MultiTurnEvalCase(
        turns=[EvalCase(message="task B", expected_tools=["tool_a"])],
        metadata={"task_id": "T_B"},
    )

    prior_turn_a = EvalTurnResult(
        case=case_a.turns[0],
        response=AgentResponse(answer="cached answer", tools_called=["tool_a"]),
        assertion_passed=True,
    )

    fleet_result = await fleet_runner.run_multi_turn_fleet(
        [case_a, case_b],
        resume_turn_results=[prior_turn_a],
    )

    assert fleet_result.resumed_cases_count == 1
    # Only case_b needs to run per attempt -> 1 case * 2 attempts = 2 calls
    assert executor.call_count == 2
    # Total results per attempt include both resumed case_a and newly run case_b
    assert len(fleet_result.primary_result.turn_results) == 2


@pytest.mark.asyncio
async def test_fleet_runner_difficulty_sharding() -> None:
    """Fleet runner filters by difficulty tier when difficulty_filter is active."""
    executor = MockExecutor()
    fleet_runner = FleetEvalRunner(executor, n_attempts=1)

    cases = [
        MultiTurnEvalCase(
            turns=[EvalCase(message="easy task", metadata={"difficulty": "easy"})],
            metadata={"difficulty": "easy"},
        ),
        MultiTurnEvalCase(
            turns=[EvalCase(message="hard task", metadata={"difficulty": "hard"})],
            metadata={"difficulty": "hard"},
        ),
    ]

    fleet_result = await fleet_runner.run_multi_turn_fleet(cases, difficulty_filter="easy")
    assert len(fleet_result.primary_result.turn_results) == 1
    assert fleet_result.primary_result.turn_results[0].case.message == "easy task"
