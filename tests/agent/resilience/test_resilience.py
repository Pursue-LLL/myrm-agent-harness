"""Unit tests for marathon task error self-correction."""

from __future__ import annotations

from myrm_agent_harness.agent.resilience.error_recovery import (
    ErrorSelfCorrectionGovernor,
)
from myrm_agent_harness.agent.resilience.types import RecoveryActionType

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
