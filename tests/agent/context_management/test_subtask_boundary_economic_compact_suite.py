# [INPUT]: CompactionDecisionResult, CompactionEconomicsCalculator, CompactionEconomicsConfig, ContinuationTurnPayload, EconomicCompactionLedger, PlanStep, PlanStepStatus, SubtaskBoundaryOnlineContextCompactAndEconomicBreakevenSuite
# [OUTPUT]: test_subtask_boundary_economic_compact_suite.py
# [POS]: tests/agent/context_management/test_subtask_boundary_economic_compact_suite.py

"""Comprehensive test suite for SubtaskBoundaryOnlineContextCompactAndEconomicBreakevenSuite.

Verifies:
1. Mathematical breakeven calculation and combined carried debt amortization.
2. Rejection of compaction when effective horizon is insufficient to avoid net token losses.
3. Proactive approval at subtask completion boundaries with ample remaining horizon.
4. Emergency hard window pressure override preventing context window exhaustion.
5. Carried debt throttling preventing destructive compaction oscillation.
6. Seamless continuation turn payload generation with structured milestone memo.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.online_economic_compact import (
    CompactionDecisionResult,
    CompactionEconomicsCalculator,
    CompactionEconomicsConfig,
    ContinuationTurnPayload,
    EconomicCompactionLedger,
    OnlineCompactContinuationEngine,
    PlanStep,
    PlanStepStatus,
    SubtaskBoundaryHook,
    SubtaskBoundaryOnlineContextCompactAndEconomicBreakevenSuite,
)


def test_mathematical_breakeven_and_carried_debt_calculation() -> None:
    config = CompactionEconomicsConfig(
        max_context_tokens=128_000,
        window_reserve_tokens=16_384,
        subsequent_compaction_margin=1.5,
    )
    calc = CompactionEconomicsCalculator(config=config)

    # Case 1: write_tokens=2400, context=10800, memo=800 -> delta=10000 -> breakeven=ceil(2400/10000)=1
    breakeven_1 = calc.calculate_breakeven(write_tokens=2400, context_tokens=10_800, memo_tokens=800)
    assert breakeven_1 == 1

    # Case 2: write_tokens=3000, context=2300, memo=800 -> delta=1500 -> breakeven=ceil(3000/1500)=2
    breakeven_2 = calc.calculate_breakeven(write_tokens=3000, context_tokens=2300, memo_tokens=800)
    assert breakeven_2 == 2

    # Case 3: Combined breakeven with carried debt of 2000 tokens -> total=5000 -> ceil(5000/1500)=4
    combined_breakeven = calc.calculate_combined_breakeven(
        write_tokens=3000, context_tokens=2300, memo_tokens=800, carried_debt_tokens=2000
    )
    assert combined_breakeven == 4


def test_insufficient_horizon_rejected() -> None:
    suite = SubtaskBoundaryOnlineContextCompactAndEconomicBreakevenSuite.create(
        window_reserve_tokens=16_384,
        max_context_tokens=128_000,
        subsequent_compaction_margin=1.5,
    )

    # Plan with only 1 remaining step, expected 1 request
    steps = [
        PlanStep(step_id="step_1", title="Setup Environment", status=PlanStepStatus.COMPLETED, requests_spent=1),
        PlanStep(step_id="step_2", title="Final Verification", status=PlanStepStatus.PENDING),
    ]
    suite.set_plan(steps)

    # Subtask boundary reached for step_1, but remaining horizon is only 2 requests while breakeven*margin > 2
    decision, payload = suite.on_subtask_completed(
        step_id="step_1",
        requests_spent=1,
        current_tokens=4000,  # delta=3200, write=2400, breakeven=1, required=ceil(1*1.5)=2
    )

    # Now test with smaller delta where breakeven is higher
    calc = suite.calculator
    small_context_steps = [
        PlanStep(step_id="s1", title="Init", status=PlanStepStatus.COMPLETED, requests_spent=1),
        PlanStep(step_id="s2", title="Done", status=PlanStepStatus.PENDING),
    ]
    res = calc.evaluate_decision(
        current_tokens=1600,  # delta=800, write=2400 -> breakeven=3 -> required=ceil(3*1.5)=5, but horizon=2
        plan_steps=small_context_steps,
        completed_step_requests=1,
        is_subtask_boundary=True,
    )
    assert not res.should_compact
    assert res.reason_code == "INSUFFICIENT_HORIZON_REJECTED"
    assert "to avoid net economic token loss" in res.explanation


def test_economic_breakeven_approved_at_subtask_boundary() -> None:
    suite = SubtaskBoundaryOnlineContextCompactAndEconomicBreakevenSuite.create()

    # Plan with 5 remaining steps
    steps = [
        PlanStep(step_id="step_1", title="Download Data", status=PlanStepStatus.PENDING),
        PlanStep(step_id="step_2", title="Clean Dataset", status=PlanStepStatus.PENDING),
        PlanStep(step_id="step_3", title="Feature Engineering", status=PlanStepStatus.PENDING),
        PlanStep(step_id="step_4", title="Train Model", status=PlanStepStatus.PENDING),
        PlanStep(step_id="step_5", title="Deploy Endpoint", status=PlanStepStatus.PENDING),
    ]
    suite.set_plan(steps)

    messages = [
        {"role": "user", "content": "Execute data pipeline."},
        {"role": "assistant", "content": "Downloading raw data files..."},
        {"role": "tool", "content": "Downloaded 50 files successfully."},
    ]

    # Complete step_1 with high context tokens (20,000 tokens)
    decision, payload = suite.on_subtask_completed(
        step_id="step_1",
        requests_spent=3,
        current_tokens=20_000,
        messages=messages,
        session_turn=1,
    )

    assert decision.should_compact is True
    assert decision.reason_code == "ECONOMIC_BREAKEVEN_APPROVED"
    assert decision.net_estimated_savings > 0
    assert payload is not None
    assert payload.new_turn_number == 2
    assert "Clean Dataset" in payload.continuation_prompt
    assert "### [SUBTASK MILESTONE MEMO]" in payload.memo_summary

    # Ledger state update
    ledger = suite.ledger
    assert ledger.total_compactions == 1
    assert ledger.lifetime_tokens_saved == decision.net_estimated_savings
    assert ledger.carried_debt_tokens == 0


def test_hard_window_pressure_override() -> None:
    suite = SubtaskBoundaryOnlineContextCompactAndEconomicBreakevenSuite.create(
        window_reserve_tokens=16_384,
        max_context_tokens=128_000,
    )

    steps = [
        PlanStep(step_id="step_single", title="Lone Step", status=PlanStepStatus.PENDING),
    ]
    suite.set_plan(steps)

    # Current tokens: 120,000. Remaining: 8,000 < window_reserve (16,384)
    decision, payload = suite.check_hard_window_pressure(
        current_tokens=120_000,
        messages=[{"role": "user", "content": "Heavy operational turn"}],
        session_turn=5,
    )

    assert decision.should_compact is True
    assert decision.reason_code == "HARD_WINDOW_PRESSURE"
    assert "hard safety reserve" in decision.explanation
    assert payload is not None
    assert payload.new_turn_number == 6


def test_carried_debt_throttling_prevents_oscillation() -> None:
    suite = SubtaskBoundaryOnlineContextCompactAndEconomicBreakevenSuite.create()

    # Manually inject prior carried debt
    suite.ledger.carried_debt_tokens = 50_000

    steps = [
        PlanStep(step_id="s1", title="Step 1", status=PlanStepStatus.COMPLETED, requests_spent=2),
        PlanStep(step_id="s2", title="Step 2", status=PlanStepStatus.PENDING),
    ]
    suite.set_plan(steps)

    # When carried debt is large and horizon is short, reject to avoid piling debt
    decision, payload = suite.on_subtask_completed(
        step_id="s1",
        requests_spent=2,
        current_tokens=5_000,
    )

    assert decision.should_compact is False
    assert decision.reason_code == "DEBT_UNRECOVERED_REJECTED"
    assert "Prior carried debt" in decision.explanation
    assert payload is None


def test_continuation_turn_state_machine() -> None:
    ledger = EconomicCompactionLedger()
    engine = OnlineCompactContinuationEngine(ledger=ledger)

    completed = [
        PlanStep(step_id="c1", title="Build Docker Image", status=PlanStepStatus.COMPLETED, requests_spent=4)
    ]
    remaining = [
        PlanStep(step_id="r1", title="Push to Registry", status=PlanStepStatus.PENDING),
        PlanStep(step_id="r2", title="Trigger Canary Deploy", status=PlanStepStatus.PENDING),
    ]

    dummy_decision = CompactionDecisionResult(
        should_compact=True,
        reason_code="ECONOMIC_BREAKEVEN_APPROVED",
        breakeven_requests=1,
        combined_breakeven_requests=1,
        effective_horizon_requests=6,
        carried_debt_tokens=0,
        net_estimated_savings=15_000,
        explanation="Approved",
    )

    payload = engine.execute_continuation(
        messages=[{"role": "tool", "content": "Docker image tagged: v1.0.0"}],
        decision=dummy_decision,
        completed_steps=completed,
        remaining_steps=remaining,
        current_tokens=25_000,
        session_turn=3,
    )

    assert payload.new_turn_number == 4
    assert "Build Docker Image" in payload.memo_summary
    assert "Push to Registry" in payload.continuation_prompt
    assert ledger.total_compactions == 1
    assert ledger.lifetime_tokens_saved == 15_000
