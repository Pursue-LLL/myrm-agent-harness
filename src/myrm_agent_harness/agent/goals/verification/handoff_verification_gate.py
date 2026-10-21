"""Adversarial verification gate that validates StructuredHandoffMemo against baseline user constraints.

[INPUT]
- agent.goals.verification.handoff_verification_types::HandoffVerificationIssue, HandoffVerificationResult,
  VerificationSeverity
- runtime.context.session_handoff_continuation_types::RejectedAlternativeRecord, StructuredHandoffMemo (POS:
  Types and models for Session Handoff and Clean Window Continuation.)

[OUTPUT]
- HandoffVerificationGate: Adversarial verification gate that validates StructuredHandoffMemo against
  baseline user constraints.

[POS]
Adversarial verification gate that validates StructuredHandoffMemo against baseline user constraints.
"""

from __future__ import annotations

from collections.abc import Sequence

from myrm_agent_harness.agent.goals.verification.handoff_verification_types import (
    HandoffVerificationIssue,
    HandoffVerificationResult,
    VerificationSeverity,
)
from myrm_agent_harness.runtime.context.session_handoff_continuation_types import (
    RejectedAlternativeRecord,
    StructuredHandoffMemo,
)


class HandoffVerificationGate:
    """Adversarial verification gate that validates StructuredHandoffMemo against baseline user constraints."""

    def __init__(self, strict_constraint_matching: bool = True) -> None:
        self.strict_constraint_matching = strict_constraint_matching

    def verify_and_rectify(
        self,
        memo: StructuredHandoffMemo,
        user_critical_constraints: Sequence[str],
        disqualified_approaches: Sequence[str] | None = None,
        auto_rectify: bool = True,
    ) -> HandoffVerificationResult:
        """Adversarially verify handoff memo against required constraints and optionally auto-rectify omissions."""
        disqualified_list = list(disqualified_approaches or [])
        issues: list[HandoffVerificationIssue] = []
        missing_constraints: list[str] = []
        missing_negatives: list[str] = []

        existing_memo_constraints = [c.lower().strip() for c in memo.critical_constraints]
        existing_memo_rejected = [r.proposed_approach.lower().strip() for r in memo.rejected_alternatives]

        # 1. Verify user critical constraints
        for required_c in user_critical_constraints:
            req_clean = required_c.lower().strip()
            # Check if required constraint is reflected in memo's critical constraints or objective
            found = any(req_clean in ec or ec in req_clean for ec in existing_memo_constraints) or (
                req_clean in memo.current_objective.lower()
            )

            if not found:
                missing_constraints.append(required_c)
                issues.append(
                    HandoffVerificationIssue(
                        severity=VerificationSeverity.CRITICAL,
                        issue_type="missing_constraint",
                        description=f"Inviolable user constraint was omitted from handoff memo: '{required_c}'",
                        offending_item=required_c,
                    )
                )

        # 2. Verify disqualified approaches / anti-regression negative decisions
        for disq in disqualified_list:
            disq_clean = disq.lower().strip()
            found_rejected = any(disq_clean in er or er in disq_clean for er in existing_memo_rejected)
            if not found_rejected:
                missing_negatives.append(disq)
                issues.append(
                    HandoffVerificationIssue(
                        severity=VerificationSeverity.WARNING,
                        issue_type="missing_negative_decision",
                        description=f"Disqualified approach was missing in handoff rejected alternatives: '{disq}'",
                        offending_item=disq,
                    )
                )

        # 3. Calculate fidelity score
        total_checks = len(user_critical_constraints) + len(disqualified_list)
        if total_checks == 0:
            fidelity_score = 1.0
        else:
            omitted_count = len(missing_constraints) + len(missing_negatives)
            fidelity_score = max(0.0, min(1.0, 1.0 - (omitted_count / total_checks)))

        passed = len(missing_constraints) == 0 and len(missing_negatives) == 0

        # 4. Self-healing auto-rectification if omissions exist
        rectified_memo: StructuredHandoffMemo | None = None
        is_rectified = False
        if not passed and auto_rectify:
            updated_constraints = list(memo.critical_constraints)
            for mc in missing_constraints:
                if mc not in updated_constraints:
                    updated_constraints.append(mc)

            updated_rejected = list(memo.rejected_alternatives)
            for mn in missing_negatives:
                if not any(r.proposed_approach == mn for r in updated_rejected):
                    updated_rejected.append(
                        RejectedAlternativeRecord(
                            proposed_approach=mn,
                            failure_reason="Restored by HandoffVerificationGate from ledger history to prevent retry",
                            prevent_retry=True,
                        )
                    )

            rectified_memo = memo.model_copy(
                update={
                    "critical_constraints": updated_constraints,
                    "rejected_alternatives": updated_rejected,
                }
            )
            is_rectified = True

        return HandoffVerificationResult(
            passed=passed,
            fidelity_score=round(fidelity_score, 3),
            issues=issues,
            missing_constraints=missing_constraints,
            missing_negative_decisions=missing_negatives,
            is_rectified=is_rectified,
            rectified_memo=rectified_memo if is_rectified else memo,
        )
