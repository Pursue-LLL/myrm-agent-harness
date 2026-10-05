"""5-Step Diagnostic Decision Tree executing standardized root cause analysis."""

import uuid
from datetime import UTC, datetime

from .models import (
    DiagnosticStepKind,
    DiagnosticStepResult,
    MemoryDiagnosticProbeContext,
    MemoryDiagnosticReport,
    MemoryRootCauseKind,
)


class FiveStepDiagnosticDecisionTree:
    """Executes sequential 5-step elimination tree to identify why memory failed to manifest."""

    def evaluate(
        self,
        context: MemoryDiagnosticProbeContext,
        session_exists: bool,
        is_session_active: bool,
        found_in_store: bool,
        found_in_pending: bool,
        is_superseded: bool,
        is_expired: bool,
        scope_matched: bool,
        scope_details: str | None,
        retrieved_rank: int | None,
        token_budget_exceeded: bool,
        model_cited: bool,
    ) -> MemoryDiagnosticReport:
        """Execute the 5-step elimination tree.

        Steps:
            1. Session State Probe: Verify session integrity and active state.
            2. Extraction Check: Verify target fact was extracted or pending review.
            3. Expiration Audit: Check if memory was superseded or expired via TTL.
            4. Scope Matching: Check multi-tenant, user, and project boundary match.
            5. Budget & Truncation: Check whether prompt budget or low rank pruned the fact.

        Args:
            context: Input probe context.
            session_exists: Whether session metadata exists in store.
            is_session_active: Whether session is currently active and valid.
            found_in_store: Whether fact was extracted into persistent store.
            found_in_pending: Whether fact is queued in pending approval.
            is_superseded: Whether fact was updated or invalidated by newer information.
            is_expired: Whether fact has passed its TTL temporal expiration.
            scope_matched: Whether query scope aligns with stored memory scope.
            scope_details: Diagnostic detail regarding scope comparison.
            retrieved_rank: Final recall ranking position (None if not recalled).
            token_budget_exceeded: Whether context budget forced truncation of this fact.
            model_cited: Whether the model explicitly referenced this fact in output.

        Returns:
            Authoritative MemoryDiagnosticReport classifying root cause.
        """
        step_results: list[DiagnosticStepResult] = []
        diag_id = f"diag-{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC)

        # -------------------------------------------------------------
        # Step 1: Session State Probe
        # -------------------------------------------------------------
        step1_passed = session_exists and is_session_active
        step_results.append(
            DiagnosticStepResult(
                step_kind=DiagnosticStepKind.STEP1_SESSION_STATE,
                passed=step1_passed,
                diagnostic_message=(
                    "Session state verified active and coherent."
                    if step1_passed
                    else f"Session '{context.session_id}' does not exist or has been abruptly terminated."
                ),
                evidence_snippet=f"exists={session_exists}, active={is_session_active}",
            )
        )
        if not step1_passed:
            return MemoryDiagnosticReport(
                diagnostic_id=diag_id,
                session_id=context.session_id,
                target_entity=context.query_target_entity,
                root_cause=MemoryRootCauseKind.SESSION_LOST,
                overall_healthy=False,
                step_results=step_results,
                remediation_advice=(
                    "Session state missing. Re-initialize conversation session and restore "
                    "StructuredTaskState anchor before retrying memory query."
                ),
                diagnosed_at=now,
            )

        # -------------------------------------------------------------
        # Step 2: Extraction Check
        # -------------------------------------------------------------
        step2_passed = found_in_store or found_in_pending
        step_results.append(
            DiagnosticStepResult(
                step_kind=DiagnosticStepKind.STEP2_EXTRACTION_CHECK,
                passed=step2_passed,
                diagnostic_message=(
                    f"Target entity '{context.query_target_entity}' was successfully extracted."
                    if step2_passed
                    else f"Target entity '{context.query_target_entity}' was NEVER extracted from dialogue."
                ),
                evidence_snippet=f"in_store={found_in_store}, in_pending={found_in_pending}",
            )
        )
        if not step2_passed:
            return MemoryDiagnosticReport(
                diagnostic_id=diag_id,
                session_id=context.session_id,
                target_entity=context.query_target_entity,
                root_cause=MemoryRootCauseKind.EXTRACTION_MISSED,
                overall_healthy=False,
                step_results=step_results,
                remediation_advice=(
                    f"Fact '{context.query_target_entity}' was missed by extraction pipeline. "
                    f"Adjust extraction heuristic or prompt to capture this entity type."
                ),
                diagnosed_at=now,
            )

        # -------------------------------------------------------------
        # Step 3: Expiration Audit
        # -------------------------------------------------------------
        step3_passed = not (is_superseded or is_expired)
        step_results.append(
            DiagnosticStepResult(
                step_kind=DiagnosticStepKind.STEP3_EXPIRATION_AUDIT,
                passed=step3_passed,
                diagnostic_message=(
                    "Fact is current, active, and within valid temporal lifespan."
                    if step3_passed
                    else f"Fact is invalid: superseded={is_superseded}, expired_by_ttl={is_expired}."
                ),
                evidence_snippet=f"superseded={is_superseded}, expired={is_expired}",
            )
        )
        if not step3_passed:
            return MemoryDiagnosticReport(
                diagnostic_id=diag_id,
                session_id=context.session_id,
                target_entity=context.query_target_entity,
                root_cause=MemoryRootCauseKind.FACT_EXPIRED_OR_SUPERSEDED,
                overall_healthy=False,
                step_results=step_results,
                remediation_advice=(
                    "Memory was intentionally retired or updated. If this fact is still valid, "
                    "review temporal expiration policy or restore superseded version."
                ),
                diagnosed_at=now,
            )

        # -------------------------------------------------------------
        # Step 4: Scope Matching
        # -------------------------------------------------------------
        step_results.append(
            DiagnosticStepResult(
                step_kind=DiagnosticStepKind.STEP4_SCOPE_MATCHING,
                passed=scope_matched,
                diagnostic_message=(
                    "Retrieval query scope matches stored memory boundary context."
                    if scope_matched
                    else f"Scope isolation mismatch: {scope_details or 'Boundary divergence.'}"
                ),
                evidence_snippet=scope_details,
            )
        )
        if not scope_matched:
            return MemoryDiagnosticReport(
                diagnostic_id=diag_id,
                session_id=context.session_id,
                target_entity=context.query_target_entity,
                root_cause=MemoryRootCauseKind.SCOPE_MISMATCH_ISOLATED,
                overall_healthy=False,
                step_results=step_results,
                remediation_advice=(
                    f"Fact was stored in a different tenant/project scope. Ensure client "
                    f"supplies matching tenant_id='{context.tenant_id}' and project_id='{context.project_id}'."
                ),
                diagnosed_at=now,
            )

        # -------------------------------------------------------------
        # Step 5: Budget & Truncation Analysis
        # -------------------------------------------------------------
        step5_passed = (retrieved_rank is not None) and (not token_budget_exceeded)
        step_results.append(
            DiagnosticStepResult(
                step_kind=DiagnosticStepKind.STEP5_BUDGET_TRUNCATION,
                passed=step5_passed,
                diagnostic_message=(
                    f"Fact injected into prompt (Rank #{retrieved_rank}, within token budget)."
                    if step5_passed
                    else f"Fact truncated or dropped (Rank={retrieved_rank}, BudgetExceeded={token_budget_exceeded})."
                ),
                evidence_snippet=f"rank={retrieved_rank}, budget_exceeded={token_budget_exceeded}",
            )
        )
        if not step5_passed:
            return MemoryDiagnosticReport(
                diagnostic_id=diag_id,
                session_id=context.session_id,
                target_entity=context.query_target_entity,
                root_cause=MemoryRootCauseKind.BUDGET_TRUNCATED_OR_RANK_DROPPED,
                overall_healthy=False,
                step_results=step_results,
                remediation_advice=(
                    f"Fact was recalled but pruned by token budget ({context.prompt_token_budget}) "
                    f"or fell below rank cutoff. Increase token budget or prune other memory namespaces."
                ),
                diagnosed_at=now,
            )

        # -------------------------------------------------------------
        # Final Synthesis: Healthy or Attention Ignored
        # -------------------------------------------------------------
        if model_cited:
            root_cause = MemoryRootCauseKind.HEALTHY
            advice = "Memory pipeline functioned flawlessly; fact was retrieved, injected, and cited."
            healthy = True
        else:
            root_cause = MemoryRootCauseKind.MODEL_ATTENTION_IGNORED
            advice = (
                "Fact was successfully injected into model prompt, but LLM ignored or overlooked "
                "it during generation. Enhance system prompt instructions to prioritize injected facts."
            )
            healthy = False

        return MemoryDiagnosticReport(
            diagnostic_id=diag_id,
            session_id=context.session_id,
            target_entity=context.query_target_entity,
            root_cause=root_cause,
            overall_healthy=healthy,
            step_results=step_results,
            remediation_advice=advice,
            diagnosed_at=now,
        )
