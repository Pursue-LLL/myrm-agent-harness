"""Plateau diagnosis engine for agent evaluations based on Meta-Harness principles.

[INPUT]
- enum, dataclasses (POS: Python standard library)

[OUTPUT]
- PlateauMechanism: canonical 4 plateau mechanisms + none
- PlateauDiagnosis: structured honest education and actionable recommendation
- diagnose_plateau(): deterministic diagnosis function based on evaluation metrics

[POS]
Meta-Harness 4-Mechanism plateau diagnosis engine for detecting hard bottlenecks,
capability saturation, insufficient statistical power, and regression noise
divergence in Agent evaluations to prevent futile prompt micro-tweaking.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class PlateauMechanism(enum.StrEnum):
    """Canonical Meta-Harness plateau diagnosis mechanisms."""

    INSUFFICIENT_POWER = "insufficient_power"  # N < 10 or (b + c) < 5
    CAPABILITY_SATURATION = "capability_saturation"  # Both pass rates >= 90%
    CROSS_MODEL_DIVERGENCE = "cross_model_divergence"  # Noise with regressions (b > 0, p >= 0.05)
    HARD_SUBSET_BOTTLENECK = "hard_subset_bottleneck"  # No discordant pairs (b + c == 0)
    NONE = "none"  # Significant change or clear signal


@dataclass(frozen=True, slots=True)
class PlateauDiagnosis:
    """Structured honest education and recommendation for evaluation plateaus."""

    mechanism: PlateauMechanism
    title: str
    explanation: str
    recommendation: str
    suggested_action: str

    def to_dict(self) -> dict[str, object]:
        return {
            "mechanism": self.mechanism.value,
            "title": self.title,
            "explanation": self.explanation,
            "recommendation": self.recommendation,
            "suggested_action": self.suggested_action,
        }


def diagnose_plateau(
    *,
    total_cases: int,
    discordant_count: int,
    base_pass_rate: float,
    cand_pass_rate: float,
    p_value: float,
    ci_crosses_zero: bool,
    regressions_count: int,
) -> PlateauDiagnosis:
    """Determine plateau mechanism based on Meta-Harness criteria.

    Evaluates whether an agent comparison has hit a hard subset bottleneck,
    capability saturation, statistical power deficit, or regression divergence.
    """
    if discordant_count == 0:
        return PlateauDiagnosis(
            mechanism=PlateauMechanism.HARD_SUBSET_BOTTLENECK,
            title="Hard Subset Bottleneck",
            explanation="Both configurations produced identical binary outcomes across all evaluated cases.",
            recommendation="Agent has hit a difficulty ceiling. Adjusting prompt is ineffective.",
            suggested_action="expand_tools_or_context",
        )

    if base_pass_rate >= 0.90 and cand_pass_rate >= 0.90:
        return PlateauDiagnosis(
            mechanism=PlateauMechanism.CAPABILITY_SATURATION,
            title="Capability Saturation",
            explanation="Both configurations achieved >=90% pass rate. Remaining failures are edge anomalies.",
            recommendation="Evaluation set is saturated for this agent capability tier.",
            suggested_action="introduce_hard_benchmark",
        )

    if total_cases < 10 or discordant_count < 5:
        return PlateauDiagnosis(
            mechanism=PlateauMechanism.INSUFFICIENT_POWER,
            title="Insufficient Statistical Power",
            explanation=f"Only {discordant_count} discordant events observed out of {total_cases} cases.",
            recommendation="Cannot distinguish true improvement from LLM sampling variance.",
            suggested_action="increase_trials_or_dataset",
        )

    if (p_value >= 0.05 or ci_crosses_zero) and regressions_count > 0:
        return PlateauDiagnosis(
            mechanism=PlateauMechanism.CROSS_MODEL_DIVERGENCE,
            title="Regression Noise Divergence",
            explanation=(
                f"New version introduced {regressions_count} regressions while difference "
                "is statistically non-significant."
            ),
            recommendation="Do not adopt this variant. It trades existing baseline capability for accidental gains.",
            suggested_action="reject_and_investigate_regressions",
        )

    return PlateauDiagnosis(
        mechanism=PlateauMechanism.NONE,
        title="Valid Signal",
        explanation="The evaluation difference exhibits clear statistical confidence without significant plateau symptoms.",
        recommendation="Safe to proceed with adoption or rejection based on effect direction.",
        suggested_action="proceed_with_gate",
    )
