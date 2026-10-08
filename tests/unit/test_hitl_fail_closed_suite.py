"""Unit tests for HITL Approval Fail-Closed Safety Gate Suite (Item 42).

[INPUT]
- NonBypassableSecondaryGuard and HitlApprovalPipeline.

[OUTPUT]
- Verified test outcomes ensuring channel disconnects, timeouts, and missing approvers fail closed,
  and invariant secondary guards block dangerous actions even when approved by humans.

[POS]
- Harness core security test suite.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.hitl_fail_closed import (
    ApprovalDecision,
    FailClosedReason,
    HitlApprovalPipeline,
    HitlFailClosedError,
    NonBypassableSecondaryGuard,
    SecondaryGuardVerdict,
    SecondaryGuardViolationError,
)


def test_non_bypassable_secondary_guard_evaluations() -> None:
    # 1. Safe command
    v_safe, _ = NonBypassableSecondaryGuard.evaluate("bash", {"command": "git status"})
    assert v_safe == SecondaryGuardVerdict.PASSED

    # 2. Destructive command
    v_dest, msg_dest = NonBypassableSecondaryGuard.evaluate("bash", {"command": "rm -rf /"})
    assert v_dest == SecondaryGuardVerdict.BLOCKED_PHYSICAL_INVARIANT
    assert "destructive pattern" in msg_dest

    # 3. Protected system file
    v_path, msg_path = NonBypassableSecondaryGuard.evaluate("file_write", {"file_path": "/etc/shadow"})
    assert v_path == SecondaryGuardVerdict.BLOCKED_HIGH_RISK_PATTERN
    assert "protected system invariant file" in msg_path


def test_hitl_pipeline_fail_closed_on_channel_disconnect() -> None:
    pipeline = HitlApprovalPipeline()

    verdict = pipeline.evaluate_execution(
        tool_name="bash",
        arguments={"command": "npm run build"},
        approver_callback=lambda: True,
        channel_connected=False,
    )
    assert verdict.approval_decision == ApprovalDecision.REJECTED_FAIL_CLOSED
    assert verdict.fail_closed_reason == FailClosedReason.CHANNEL_DISCONNECTED
    assert verdict.is_execution_permitted is False

    with pytest.raises(HitlFailClosedError):
        pipeline.assert_execution_permitted(
            tool_name="bash",
            arguments={"command": "npm run build"},
            approver_callback=lambda: True,
            channel_connected=False,
        )


def test_hitl_pipeline_fail_closed_on_timeout_and_missing_service() -> None:
    pipeline = HitlApprovalPipeline()

    # 1. Service missing
    v_missing = pipeline.evaluate_execution(
        tool_name="bash",
        arguments={"command": "npm install"},
        approver_callback=None,
    )
    assert v_missing.approval_decision == ApprovalDecision.REJECTED_FAIL_CLOSED
    assert v_missing.fail_closed_reason == FailClosedReason.SERVICE_UNAVAILABLE

    # 2. Approver timeout
    def _timeout_approver() -> bool:
        raise TimeoutError("Reviewer did not respond in 30 seconds.")

    v_timeout = pipeline.evaluate_execution(
        tool_name="bash",
        arguments={"command": "npm install"},
        approver_callback=_timeout_approver,
    )
    assert v_timeout.approval_decision == ApprovalDecision.REJECTED_FAIL_CLOSED
    assert v_timeout.fail_closed_reason == FailClosedReason.TIMEOUT


def test_hitl_pipeline_user_rejection_vs_approval() -> None:
    pipeline = HitlApprovalPipeline()

    # Explicit user rejection
    v_rej = pipeline.evaluate_execution(
        tool_name="bash",
        arguments={"command": "npm run deploy"},
        approver_callback=lambda: False,
    )
    assert v_rej.approval_decision == ApprovalDecision.REJECTED_USER
    assert v_rej.is_execution_permitted is False

    # Explicit user approval + safe command
    v_ok = pipeline.evaluate_execution(
        tool_name="bash",
        arguments={"command": "npm run test"},
        approver_callback=lambda: True,
    )
    assert v_ok.approval_decision == ApprovalDecision.APPROVED
    assert v_ok.guard_verdict == SecondaryGuardVerdict.PASSED
    assert v_ok.is_execution_permitted is True


def test_hitl_pipeline_invariant_guard_blocks_approved_destructive_action() -> None:
    pipeline = HitlApprovalPipeline()

    # Human mistakenly approves "rm -rf /"
    v_blocked = pipeline.evaluate_execution(
        tool_name="bash",
        arguments={"command": "rm -rf /"},
        approver_callback=lambda: True,
    )

    # Human approved, but secondary guard blocked!
    assert v_blocked.approval_decision == ApprovalDecision.APPROVED
    assert v_blocked.guard_verdict == SecondaryGuardVerdict.BLOCKED_PHYSICAL_INVARIANT
    assert v_blocked.is_execution_permitted is False
    assert "destructive pattern" in v_blocked.audit_rationale

    with pytest.raises(SecondaryGuardViolationError):
        pipeline.assert_execution_permitted(
            tool_name="bash",
            arguments={"command": "rm -rf /"},
            approver_callback=lambda: True,
        )
