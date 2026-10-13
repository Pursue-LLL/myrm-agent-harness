"""Pure-rule skill health evaluator driven by observed run outcomes.

[INPUT]
- myrm_agent_harness.observability.digest.types::(SkillCompoundingMetrics, SkillHealthScore, SkillHealthStatus) (POS: 周报数据契约)

[OUTPUT]
- SkillHealthEvaluator: Turns a skill's observed outcomes into a confidence-weighted score and a status

[POS]
Harness-level skill health analytics without LLM overhead. Only quantities a caller actually measured
take part: the success rate of runs with an observed outcome, trusted in proportion to how many
outcomes back it. A skill with too few outcomes is UNPROVEN, never STAR or AT_RISK.
"""

from __future__ import annotations

from datetime import UTC, datetime

from myrm_agent_harness.observability.digest.types import (
    SkillCompoundingMetrics,
    SkillHealthScore,
    SkillHealthStatus,
)

_STAR_MIN_SUCCESS_RATE = 0.90
_AT_RISK_MAX_SUCCESS_RATE = 0.65
_STALE_SCORE = 15.0


class SkillHealthEvaluator:
    """Scores a skill by its observed success rate, weighted by the amount of evidence."""

    @classmethod
    def evaluate(
        cls,
        metrics: SkillCompoundingMetrics,
        *,
        min_observed: int,
        reference_time: datetime | None = None,
        stale_days_threshold: int = 30,
    ) -> SkillHealthScore:
        """Compute the health score and classify the skill.

        ``min_observed`` is the number of observed outcomes needed before the success rate is trusted
        in full; with fewer outcomes the score is scaled down proportionally and the status is UNPROVEN.
        """
        now = reference_time or datetime.now(UTC)
        observed = metrics.successful_invocations + metrics.failed_invocations
        success_rate = metrics.successful_invocations / observed if observed > 0 else None
        reported_rate = round(success_rate, 4) if success_rate is not None else None

        if metrics.invocations <= 0:
            return SkillHealthScore(
                skill_id=metrics.skill_id,
                health_score=0.0,
                status=SkillHealthStatus.STALE,
                success_rate=None,
                actionable_recommendation="Skill has not been invoked. Consider deprecating or adding examples.",
            )

        if metrics.last_invoked_at:
            delta_days = (now - metrics.last_invoked_at).total_seconds() / 86400.0
            if delta_days > stale_days_threshold:
                return SkillHealthScore(
                    skill_id=metrics.skill_id,
                    health_score=_STALE_SCORE,
                    status=SkillHealthStatus.STALE,
                    success_rate=reported_rate,
                    actionable_recommendation=f"Inactive for {int(delta_days)} days. Review for obsolescence.",
                )

        required = max(1, min_observed)
        if success_rate is None or observed < required:
            return SkillHealthScore(
                skill_id=metrics.skill_id,
                health_score=round(100.0 * (success_rate or 0.0) * (observed / required), 2),
                status=SkillHealthStatus.UNPROVEN,
                success_rate=reported_rate,
                actionable_recommendation=(
                    f"Too few observed outcomes to judge quality yet ({observed} of {required} needed)."
                ),
            )

        if success_rate >= _STAR_MIN_SUCCESS_RATE:
            status = SkillHealthStatus.STAR
            recommendation = "Star asset! Highly reliable across observed runs."
        elif success_rate < _AT_RISK_MAX_SUCCESS_RATE:
            status = SkillHealthStatus.AT_RISK
            recommendation = "At-risk asset. High failure rate detected; review prompt and parameters."
        else:
            status = SkillHealthStatus.HEALTHY
            recommendation = "Healthy asset in active rotation."

        return SkillHealthScore(
            skill_id=metrics.skill_id,
            health_score=round(100.0 * success_rate, 2),
            status=status,
            success_rate=reported_rate,
            actionable_recommendation=recommendation,
        )
