"""Unit tests for Per-Role Subagent Failure Restart & Redeploy Policy (Item 35).

[INPUT]
- myrm_agent_harness.agent.sub_agents.failure_policy::{
    FailureAction,
    FailureEvent,
    FailureTriggerReason,
    RoleFailurePolicy,
    RoleFailurePolicyEngine,
  }

[OUTPUT]
- Pytest cases verifying autonomous restart with fresh instructions,
  spec-redeploy parameter adjustment, non-fatal skip decisions, and retry bound escalation.

[POS]
- myrm-agent-harness/tests/agent/sub_agents/test_failure_policy.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.sub_agents.failure_policy import (
    FailureAction,
    FailureEvent,
    FailureTriggerReason,
    RoleFailurePolicy,
    RoleFailurePolicyEngine,
)


@pytest.fixture
def engine() -> RoleFailurePolicyEngine:
    return RoleFailurePolicyEngine()


def test_default_policy_restart_fresh(engine: RoleFailurePolicyEngine) -> None:
    event1 = FailureEvent(
        event_id="evt_01",
        task_id="task_worker_1",
        role_key="coder",
        trigger_reason=FailureTriggerReason.CRASH_ERROR,
        error_message="ZeroDivisionError in calculate_metrics",
    )

    decision1 = engine.evaluate_failure(event1)
    assert decision1.action == FailureAction.RESTART_FRESH
    assert decision1.attempt_number == 1
    assert decision1.max_retries == 2
    assert "fresh_instructions" in decision1.redeploy_payload
    assert "ZeroDivisionError" in decision1.redeploy_payload["fresh_instructions"]


def test_exceeded_max_retries_escalates(engine: RoleFailurePolicyEngine) -> None:
    task_id = "task_worker_flake"
    role_key = "coder"

    # Attempt 1
    d1 = engine.evaluate_failure(
        FailureEvent(
            event_id="e1",
            task_id=task_id,
            role_key=role_key,
            trigger_reason=FailureTriggerReason.STUCK_TIMEOUT,
            error_message="Execution timed out after 300s",
        )
    )
    assert d1.action == FailureAction.RESTART_FRESH
    assert d1.attempt_number == 1

    # Attempt 2
    d2 = engine.evaluate_failure(
        FailureEvent(
            event_id="e2",
            task_id=task_id,
            role_key=role_key,
            trigger_reason=FailureTriggerReason.STUCK_TIMEOUT,
            error_message="Execution timed out again",
        )
    )
    assert d2.action == FailureAction.RESTART_FRESH
    assert d2.attempt_number == 2

    # Attempt 3 -> Exceeds max_retries (2)
    d3 = engine.evaluate_failure(
        FailureEvent(
            event_id="e3",
            task_id=task_id,
            role_key=role_key,
            trigger_reason=FailureTriggerReason.STUCK_TIMEOUT,
            error_message="Fatal stuck",
        )
    )
    assert d3.action == FailureAction.ESCALATE_PARENT
    assert d3.attempt_number == 3
    assert "exceeded max retries limit" in d3.rationale


def test_allow_failure_skips_on_spec_mismatch(engine: RoleFailurePolicyEngine) -> None:
    # Scout researcher allows failure
    engine.register_policy(
        RoleFailurePolicy(
            role_key="researcher",
            primary_action=FailureAction.RESTART_FRESH,
            allow_failure=True,
            max_retries=1,
        )
    )

    event = FailureEvent(
        event_id="evt_scout_01",
        task_id="task_scout_99",
        role_key="researcher",
        trigger_reason=FailureTriggerReason.OUTPUT_SPEC_MISMATCH,
        error_message="External documentation site returned 404",
    )

    decision = engine.evaluate_failure(event)
    assert decision.action == FailureAction.SKIP
    assert "allows failure on non-blocking reason" in decision.rationale


def test_redeploy_specs_action(engine: RoleFailurePolicyEngine) -> None:
    engine.register_policy(
        RoleFailurePolicy(
            role_key="synthesizer",
            primary_action=FailureAction.REDEPLOY_SPECS,
            max_retries=3,
            redeploy_model_tier_downgrade=True,
        )
    )

    event = FailureEvent(
        event_id="evt_synth_01",
        task_id="task_synth_12",
        role_key="synthesizer",
        trigger_reason=FailureTriggerReason.TOOL_QUOTA_EXHAUSTED,
        error_message="Subagent hit 30 tool calls limit",
    )

    decision = engine.evaluate_failure(event)
    assert decision.action == FailureAction.REDEPLOY_SPECS
    assert decision.redeploy_payload.get("downgrade_model_tier") == "true"
    assert "remediated_spec" in decision.redeploy_payload


def test_reset_and_history_retrieval(engine: RoleFailurePolicyEngine) -> None:
    task_id = "task_reset_test"
    engine.evaluate_failure(
        FailureEvent(
            event_id="evt_rst_01",
            task_id=task_id,
            role_key="tester",
            trigger_reason=FailureTriggerReason.CRASH_ERROR,
            error_message="Test failure",
        )
    )

    history = engine.get_history(task_id=task_id)
    assert len(history) == 1
    assert history[0].task_id == task_id

    # Reset retry count and evaluate again
    engine.reset_retry_count(task_id)
    d_after_reset = engine.evaluate_failure(
        FailureEvent(
            event_id="evt_rst_02",
            task_id=task_id,
            role_key="tester",
            trigger_reason=FailureTriggerReason.CRASH_ERROR,
            error_message="Test failure second run",
        )
    )
    assert d_after_reset.attempt_number == 1  # Reset back to 1
