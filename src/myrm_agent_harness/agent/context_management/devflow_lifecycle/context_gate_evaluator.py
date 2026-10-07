"""The 4-Question Context Gate Evaluator governing information admission into active memory.

Applies strict admission heuristics based on phase necessity, single-use isolation,
trigger conditions, and external URI indexability.
"""

from __future__ import annotations

from .devflow_types import (
    ContextAdmissionDecision,
    DevFlowPhase,
    GateQuestionnaireEvaluation,
)


class ContextGateEvaluator:
    """Evaluates whether prospective content is admitted directly, deferred, isolated, or referenced."""

    def evaluate_admission(
        self,
        current_phase: DevFlowPhase,
        intended_phase: DevFlowPhase,
        content_length: int,
        is_single_use: bool = False,
        has_trigger_condition: bool = False,
        trigger_satisfied: bool = False,
        can_external_lookup: bool = False,
    ) -> GateQuestionnaireEvaluation:
        """Apply the 4-Question Gate questionnaire to determine content context placement."""
        # Q1: Is it strictly required for the CURRENT phase?
        is_required = current_phase == intended_phase

        # Q2: Is it a one-off single-use reference (e.g. raw shell grep or log dump)?
        is_single_use_ref = is_single_use

        # Q3: Does it have an explicit trigger condition?
        has_trigger = has_trigger_condition
        trigger_active = trigger_satisfied if has_trigger else True

        # Q4: Can it be reliably re-fetched or referenced externally by path/URI?
        can_lookup = can_external_lookup

        # Decision reasoning
        if not is_required or (has_trigger and not trigger_active):
            return GateQuestionnaireEvaluation(
                is_required_for_current_phase=is_required,
                is_single_use_reference=is_single_use_ref,
                has_explicit_trigger_condition=has_trigger,
                can_be_retrieved_externally=can_lookup,
                decision=ContextAdmissionDecision.DEFER_PROGRESSIVE,
                rationale=(
                    f"Deferred: content belongs to {intended_phase.value} (current: {current_phase.value}) "
                    f"or trigger condition unsatisfied."
                ),
            )

        if is_single_use_ref:
            return GateQuestionnaireEvaluation(
                is_required_for_current_phase=is_required,
                is_single_use_reference=True,
                has_explicit_trigger_condition=has_trigger,
                can_be_retrieved_externally=can_lookup,
                decision=ContextAdmissionDecision.ISOLATE_SCRATCHPAD,
                rationale="Isolated: single-use exploratory payload must be confined to scratchpad/subagent.",
            )

        if can_lookup and content_length > 800:
            return GateQuestionnaireEvaluation(
                is_required_for_current_phase=is_required,
                is_single_use_reference=False,
                has_explicit_trigger_condition=has_trigger,
                can_be_retrieved_externally=True,
                decision=ContextAdmissionDecision.EXTERNAL_REFERENCE_ONLY,
                rationale=f"Reference only: payload ({content_length} chars) is externally fetchable on-demand.",
            )

        return GateQuestionnaireEvaluation(
            is_required_for_current_phase=True,
            is_single_use_reference=False,
            has_explicit_trigger_condition=has_trigger,
            can_be_retrieved_externally=False,
            decision=ContextAdmissionDecision.INLINE_ALLOW,
            rationale="Admitted: content passes all 4 questions and is required in the active turn.",
        )
