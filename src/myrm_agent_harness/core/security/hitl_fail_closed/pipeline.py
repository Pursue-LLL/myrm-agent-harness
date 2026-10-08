"""Two-Phase HITL Approval Pipeline enforcing strict Fail-Closed semantics and invariant guards.

[INPUT]
- Tool names, argument mappings, human approval callbacks, and channel connectivity flags.

[OUTPUT]
- HitlExecutionPipelineVerdict determining whether execution is permitted with audit rationale.

[POS]
- Harness core security pipeline guaranteeing zero silent approval on communication failure
  and enforcing non-bypassable secondary safety invariants.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from myrm_agent_harness.core.security.hitl_fail_closed.secondary_guard import (
    NonBypassableSecondaryGuard,
)
from myrm_agent_harness.core.security.hitl_fail_closed.types import (
    ApprovalDecision,
    FailClosedReason,
    HitlExecutionPipelineVerdict,
    HitlFailClosedError,
    SecondaryGuardVerdict,
    SecondaryGuardViolationError,
)


class HitlApprovalPipeline:
    """Coordinates two-phase execution gating: Fail-Closed Human Approval + Invariant Secondary Guard."""

    def __init__(self, guard: type[NonBypassableSecondaryGuard] = NonBypassableSecondaryGuard) -> None:
        self._guard = guard

    def evaluate_execution(
        self,
        tool_name: str,
        arguments: dict[str, str],
        approver_callback: Callable[[], bool] | None = None,
        channel_connected: bool = True,
        is_service_available: bool = True,
    ) -> HitlExecutionPipelineVerdict:
        """Evaluate tool execution through two-phase gating with strict fail-closed safety."""
        audit_id = f"hitl-{uuid.uuid4().hex[:12]}"

        # Phase 1: Check channel connectivity
        if not channel_connected:
            return HitlExecutionPipelineVerdict(
                tool_name=tool_name,
                arguments=arguments,
                approval_decision=ApprovalDecision.REJECTED_FAIL_CLOSED,
                fail_closed_reason=FailClosedReason.CHANNEL_DISCONNECTED,
                guard_verdict=SecondaryGuardVerdict.PASSED,
                is_execution_permitted=False,
                audit_id=audit_id,
                audit_rationale="HITL fail-closed: approval channel (WebSocket/relay) is disconnected.",
            )

        # Check approval service availability
        if not is_service_available or approver_callback is None:
            return HitlExecutionPipelineVerdict(
                tool_name=tool_name,
                arguments=arguments,
                approval_decision=ApprovalDecision.REJECTED_FAIL_CLOSED,
                fail_closed_reason=FailClosedReason.SERVICE_UNAVAILABLE,
                guard_verdict=SecondaryGuardVerdict.PASSED,
                is_execution_permitted=False,
                audit_id=audit_id,
                audit_rationale="HITL fail-closed: human approval service component is missing or unavailable.",
            )

        # Invoke human approver callback with exception handling
        try:
            approved = approver_callback()
        except TimeoutError:
            return HitlExecutionPipelineVerdict(
                tool_name=tool_name,
                arguments=arguments,
                approval_decision=ApprovalDecision.REJECTED_FAIL_CLOSED,
                fail_closed_reason=FailClosedReason.TIMEOUT,
                guard_verdict=SecondaryGuardVerdict.PASSED,
                is_execution_permitted=False,
                audit_id=audit_id,
                audit_rationale="HITL fail-closed: reviewer approval response timed out.",
            )
        except Exception as exc:
            return HitlExecutionPipelineVerdict(
                tool_name=tool_name,
                arguments=arguments,
                approval_decision=ApprovalDecision.REJECTED_FAIL_CLOSED,
                fail_closed_reason=FailClosedReason.TRANSPORT_ERROR,
                guard_verdict=SecondaryGuardVerdict.PASSED,
                is_execution_permitted=False,
                audit_id=audit_id,
                audit_rationale=f"HITL fail-closed: unexpected error during approval communication ({exc}).",
            )

        if not approved:
            return HitlExecutionPipelineVerdict(
                tool_name=tool_name,
                arguments=arguments,
                approval_decision=ApprovalDecision.REJECTED_USER,
                fail_closed_reason=FailClosedReason.NONE,
                guard_verdict=SecondaryGuardVerdict.PASSED,
                is_execution_permitted=False,
                audit_id=audit_id,
                audit_rationale="Human reviewer explicitly rejected tool execution request.",
            )

        # Phase 2: Non-bypassable secondary invariant guard
        guard_verdict, guard_msg = self._guard.evaluate(tool_name=tool_name, arguments=arguments)
        if guard_verdict != SecondaryGuardVerdict.PASSED:
            return HitlExecutionPipelineVerdict(
                tool_name=tool_name,
                arguments=arguments,
                approval_decision=ApprovalDecision.APPROVED,
                fail_closed_reason=FailClosedReason.NONE,
                guard_verdict=guard_verdict,
                is_execution_permitted=False,
                audit_id=audit_id,
                audit_rationale=f"Invariant violation: {guard_msg}",
            )

        return HitlExecutionPipelineVerdict(
            tool_name=tool_name,
            arguments=arguments,
            approval_decision=ApprovalDecision.APPROVED,
            fail_closed_reason=FailClosedReason.NONE,
            guard_verdict=SecondaryGuardVerdict.PASSED,
            is_execution_permitted=True,
            audit_id=audit_id,
            audit_rationale="Tool execution authorized by human reviewer and verified by invariant safety guard.",
        )

    def assert_execution_permitted(
        self,
        tool_name: str,
        arguments: dict[str, str],
        approver_callback: Callable[[], bool] | None = None,
        channel_connected: bool = True,
        is_service_available: bool = True,
    ) -> HitlExecutionPipelineVerdict:
        """Evaluate execution and raise corresponding domain exception if rejected or blocked."""
        verdict = self.evaluate_execution(
            tool_name=tool_name,
            arguments=arguments,
            approver_callback=approver_callback,
            channel_connected=channel_connected,
            is_service_available=is_service_available,
        )

        if verdict.fail_closed_reason != FailClosedReason.NONE:
            raise HitlFailClosedError(verdict.audit_rationale)
        if verdict.approval_decision == ApprovalDecision.REJECTED_USER:
            raise HitlFailClosedError(verdict.audit_rationale)
        if verdict.guard_verdict != SecondaryGuardVerdict.PASSED:
            raise SecondaryGuardViolationError(verdict.audit_rationale)

        return verdict
