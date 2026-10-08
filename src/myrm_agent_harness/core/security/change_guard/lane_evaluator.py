"""ChangeGuard decision lane evaluator (Lane A vs Lane B).

[INPUT]
- Hardened findings, active policy configuration.

[OUTPUT]
- LaneDecisionSummary for Lane A (deterministic gates) and Lane B (review questions).

[POS]
- Evaluator core enforcing review floor and lane separation (WS1, WS2, WS3).
"""

from __future__ import annotations

from typing import Final

from .types import (
    CanonicalOutcome,
    ChangeClass,
    ChangeGuardPolicyConfig,
    DecisionLane,
    Gateability,
    HardenedFinding,
    LaneDecisionSummary,
    ProvenanceClass,
)

_DEFINITION_PREFIXES: Final[tuple[str, ...]] = (
    "PROMPT_",
    "PROMPT_FILE_",
    "SKILL_",
    "TOOL_DEF_",
    "MODEL_CONFIG_",
    "WORKFLOW_",
    "CC_",
)

_CHANGE_SEVERITY_ORDER: Final[dict[ChangeClass, int]] = {
    ChangeClass.NO_CHANGE: 0,
    ChangeClass.UNKNOWN: 1,
    ChangeClass.LOW_CHANGE: 2,
    ChangeClass.MATERIAL_CHANGE: 3,
    ChangeClass.HIGH_RISK_CHANGE: 4,
}


def get_highest_change_class(findings: tuple[HardenedFinding, ...]) -> ChangeClass:
    """Calculate the maximum change materiality class across findings."""
    if not findings:
        return ChangeClass.NO_CHANGE
    highest = ChangeClass.NO_CHANGE
    highest_score = 0
    for f in findings:
        score = _CHANGE_SEVERITY_ORDER.get(f.change_class, 0)
        if score > highest_score:
            highest_score = score
            highest = f.change_class
    return highest


def is_definition_rule(rule_id: str) -> bool:
    """Determine if a rule ID represents an agent/prompt/skill/tool definition."""
    return any(rule_id.startswith(prefix) for prefix in _DEFINITION_PREFIXES)


class ChangeGuardLaneEvaluator:
    """Evaluates findings into separate Lane A (gates) and Lane B (review questions)."""

    def __init__(self, config: ChangeGuardPolicyConfig | None = None) -> None:
        self._config = config or ChangeGuardPolicyConfig()

    def evaluate_lanes(
        self,
        findings: tuple[HardenedFinding, ...],
    ) -> tuple[LaneDecisionSummary, LaneDecisionSummary, ChangeClass]:
        """Separate findings into Lane A and Lane B, evaluating outcomes strictly."""
        lane_a_findings: list[HardenedFinding] = []
        lane_b_findings: list[HardenedFinding] = []
        review_questions: list[str] = []

        highest_change = get_highest_change_class(findings)

        has_definition_change = False

        for f in findings:
            if is_definition_rule(f.rule_id):
                has_definition_change = True

            # Inferred or heuristic findings cannot trip Lane A deterministic gates
            is_deterministic = (
                f.gateability == Gateability.DETERMINISTIC
                and f.provenance_class in (ProvenanceClass.DECLARED, ProvenanceClass.DETECTED)
            )

            if is_deterministic:
                lane_a_findings.append(f)
            else:
                lane_b_findings.append(f)
                question = f"[{f.rule_id}] Review required for {f.target_object}: {f.message}"
                review_questions.append(question)

        # 1. Evaluate Lane A (Deterministic Gates)
        lane_a_outcome = CanonicalOutcome.PASS
        if self._config.fail_on_authority_change is not None:
            threshold_score = _CHANGE_SEVERITY_ORDER[self._config.fail_on_authority_change]
            # Authority change gate requires deterministic backing
            deterministic_highest = get_highest_change_class(tuple(lane_a_findings))
            if _CHANGE_SEVERITY_ORDER.get(deterministic_highest, 0) >= threshold_score:
                lane_a_outcome = CanonicalOutcome.BLOCK

        # Check for any explicit high-risk blocking findings in Lane A
        for f in lane_a_findings:
            if f.change_class == ChangeClass.HIGH_RISK_CHANGE:
                lane_a_outcome = CanonicalOutcome.BLOCK
                break

        # 2. Evaluate Lane B (Mandatory Review Questions & Review Floor)
        lane_b_outcome = CanonicalOutcome.PASS
        if review_questions:
            lane_b_outcome = CanonicalOutcome.REVIEW_REQUIRED
        elif self._config.enforce_definition_review_floor and has_definition_change:
            # Enforce review floor: new/changed definitions require at least human review
            lane_b_outcome = CanonicalOutcome.REVIEW_REQUIRED
            review_questions.append(
                "Review floor triggered: prompt/tool/skill definition modifications require manual signoff."
            )

        summary_a = LaneDecisionSummary(
            lane=DecisionLane.LANE_A,
            outcome=lane_a_outcome,
            findings=tuple(lane_a_findings),
            unresolved_questions=(),
        )

        summary_b = LaneDecisionSummary(
            lane=DecisionLane.LANE_B,
            outcome=lane_b_outcome,
            findings=tuple(lane_b_findings),
            unresolved_questions=tuple(review_questions),
        )

        return summary_a, summary_b, highest_change
