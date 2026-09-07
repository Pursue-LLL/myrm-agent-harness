"""Unit tests for marathon task error self-correction and execution budget governance."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from myrm_agent_harness.agent.resilience.budget_controller import (
    DynamicExecutionBudgetController,
)
from myrm_agent_harness.agent.resilience.checkpointer import (
    MarathonCheckpointer,
)
from myrm_agent_harness.agent.resilience.error_recovery import (
    ErrorSelfCorrectionGovernor,
)
from myrm_agent_harness.agent.resilience.types import (
    ExecutionBudgetConfig,
    RecoveryActionType,
)


# ============================================================================
# ErrorSelfCorrectionGovernor Tests
# ============================================================================


def test_error_self_correction_dependency_recovery():
    """Verify Missing Module error produces an ENV_REPAIR recovery action."""
    governor = ErrorSelfCorrectionGovernor(max_recovery_attempts=2)
    outcome = governor.diagnose_and_suggest_repair(
        operation="run_script",
        target="script.py",
        error_message="ModuleNotFoundError: No module named 'requests'",
        attempt=1,
    )

    assert outcome.success is True
    assert outcome.action_taken == RecoveryActionType.ENV_REPAIR
    assert "requests" in outcome.diagnostic_details
    assert outcome.fallback_message is None


def test_error_self_correction_file_not_found():
    """Verify FileNotFoundError triggers SANITIZE_INPUT strategy."""
    governor = ErrorSelfCorrectionGovernor(max_recovery_attempts=2)
    outcome = governor.diagnose_and_suggest_repair(
        operation="read_file",
        target="/tmp/missing_file.txt",
        error_message="FileNotFoundError: [Errno 2] No such file or directory: '/tmp/missing_file.txt'",
        attempt=1,
    )

    assert outcome.success is True
    assert outcome.action_taken == RecoveryActionType.SANITIZE_INPUT
    assert "Target path does not exist" in outcome.diagnostic_details


def test_error_self_correction_network_timeout():
    """Verify TimeoutError triggers RETRY strategy."""
    governor = ErrorSelfCorrectionGovernor(max_recovery_attempts=2)
    outcome = governor.diagnose_and_suggest_repair(
        operation="fetch_url",
        target="https://example.com/api",
        error_message="TimeoutError: Connection timed out after 30000ms",
        attempt=1,
    )

    assert outcome.success is True
    assert outcome.action_taken == RecoveryActionType.RETRY


def test_error_self_correction_max_attempts_escalation():
    """Verify exceeding max attempts triggers ESCALATE."""
    governor = ErrorSelfCorrectionGovernor(max_recovery_attempts=2)
    outcome = governor.diagnose_and_suggest_repair(
        operation="run_script",
        target="script.py",
        error_message="Some persistent runtime failure",
        attempt=3,
    )

    assert outcome.success is False
    assert outcome.action_taken == RecoveryActionType.ESCALATE
    assert outcome.fallback_message is not None
    assert "Self-correction ceiling reached" in outcome.fallback_message


# ============================================================================
# DynamicExecutionBudgetController Tests
# ============================================================================


def test_budget_controller_step_limit():
    """Verify step limit breaching triggers violation."""
    config = ExecutionBudgetConfig(max_steps_per_task=5)
    controller = DynamicExecutionBudgetController(config)

    for i in range(4):
        controller.record_step(f"step_{i}")
        assert controller.check_budget_violation() is None

    controller.record_step("step_4")
    violation = controller.check_budget_violation()
    assert violation is not None
    assert "Step quota exceeded" in violation

    snapshot = controller.get_snapshot()
    assert snapshot.is_exhausted is True
    assert snapshot.total_steps == 5


def test_budget_controller_token_limit():
    """Verify total token limit breaching triggers violation."""
    config = ExecutionBudgetConfig(max_tokens_total=1000)
    controller = DynamicExecutionBudgetController(config)

    controller.record_token_usage(prompt_tokens=400, completion_tokens=400)
    assert controller.check_budget_violation() is None

    controller.record_token_usage(prompt_tokens=200, completion_tokens=100)
    violation = controller.check_budget_violation()
    assert violation is not None
    assert "Token budget exceeded" in violation


def test_budget_controller_consecutive_error_breaker():
    """Verify consecutive error circuit breaker trips and resets on success."""
    config = ExecutionBudgetConfig(max_consecutive_errors=3)
    controller = DynamicExecutionBudgetController(config)

    controller.record_error("Err 1")
    controller.record_error("Err 2")
    assert controller.check_budget_violation() is None

    controller.record_success()
    assert controller.get_snapshot().consecutive_errors == 0

    controller.record_error("Err 1")
    controller.record_error("Err 2")
    controller.record_error("Err 3")
    violation = controller.check_budget_violation()
    assert violation is not None
    assert "Consecutive error breaker tripped" in violation


# ============================================================================
# MarathonCheckpointer Tests
# ============================================================================


def test_marathon_checkpointer_lifecycle(tmp_path: Path):
    """Verify saving, listing, loading, and purging checkpoints."""
    checkpointer = MarathonCheckpointer(storage_dir=tmp_path)
    session_id = "test-session-marathon-1"

    # Save step 1
    chk1 = checkpointer.save_checkpoint(
        session_id=session_id,
        step_index=1,
        step_name="Step 1: Setup",
        completed_steps=["Init"],
        pending_steps=["Execute", "Deliver"],
        state_payload={"key": "val1"},
    )
    assert chk1.checkpoint_id.startswith(f"chk-{session_id}-0001-")

    # Save step 2
    chk2 = checkpointer.save_checkpoint(
        session_id=session_id,
        step_index=2,
        step_name="Step 2: Execute",
        completed_steps=["Init", "Setup"],
        pending_steps=["Deliver"],
        state_payload={"key": "val2"},
    )

    # List
    checkpoints = checkpointer.list_checkpoints(session_id)
    assert len(checkpoints) == 2
    assert checkpoints[0].step_index == 1
    assert checkpoints[1].step_index == 2

    # Load latest
    latest = checkpointer.load_latest_checkpoint(session_id)
    assert latest is not None
    assert latest.step_index == 2
    assert latest.state_payload == {"key": "val2"}

    # Purge
    checkpointer.purge_session(session_id)
    assert checkpointer.load_latest_checkpoint(session_id) is None
    assert len(checkpointer.list_checkpoints(session_id)) == 0
