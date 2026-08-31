"""Pure-rule Multi-dimensional Skill Health and Compounding Evaluator.

[INPUT]
- myrm_agent_harness.observability.digest.types::(SkillCompoundingMetrics, SkillHealthScore, SkillHealthStatus) (POS: 周报数据契约)

[OUTPUT]
- SkillHealthEvaluator: Evaluates raw usage metrics into composite scores and classifications

[POS]
Harness-level skill compounding analytics evaluating adoption, error convergence, and cross-session reuse without LLM overhead.
"""

from __future__ import annotations

from datetime import datetime, timezone

from myrm_agent_harness.observability.digest.types import (
    SkillCompoundingMetrics,
    SkillHealthScore,
    SkillHealthStatus,
)


class SkillHealthEvaluator:
    """Evaluates skill compounding index and health classification using weighted pure rules."""

    @classmethod
    def evaluate(
        cls,
        metrics: SkillCompoundingMetrics,
        *,
        reference_time: datetime | None = None,
        stale_days_threshold: int = 30,
    ) -> SkillHealthScore:
        """Compute composite health score and classify skill status."""
        now = reference_time or datetime.now(timezone.utc)

        # 1. Handle dormant / stale skills (0 invocations or inactive > 30 days)
        if metrics.invocations <= 0:
            return SkillHealthScore(
                skill_id=metrics.skill_id,
                health_score=0.0,
                status=SkillHealthStatus.STALE,
                adoption_rate=0.0,
                success_rate=0.0,
                reuse_breadth=0.0,
                actionable_recommendation="Skill has not been invoked. Consider deprecating or adding examples.",
            )

        if metrics.last_invoked_at:
            delta_days = (now - metrics.last_invoked_at).total_seconds() / 86400.0
            if delta_days > stale_days_threshold:
                return SkillHealthScore(
                    skill_id=metrics.skill_id,
                    health_score=15.0,
                    status=SkillHealthStatus.STALE,
                    adoption_rate=0.0,
                    success_rate=metrics.successful_invocations / metrics.invocations,
                    reuse_breadth=metrics.distinct_sessions / metrics.invocations,
                    actionable_recommendation=f"Inactive for {int(delta_days)} days. Review for obsolescence.",
                )

        # 2. Compute individual dimensional ratios
        success_rate = min(1.0, max(0.0, metrics.successful_invocations / metrics.invocations))
        adoption_rate = min(1.0, max(0.0, metrics.adopted_outputs / metrics.invocations))
        reuse_breadth = min(1.0, max(0.0, metrics.distinct_sessions / metrics.invocations))
        retry_penalty = min(0.5, (metrics.retry_count / metrics.invocations) * 0.25)

        # 3. Weighted composite calculation:
        # - Adoption Rate (40%)
        # - Success Rate (30%)
        # - Reuse Breadth (20%)
        # - Invocations Bonus (up to 10% for >= 20 calls)
        # - Minus Retry Penalty
        volume_factor = min(1.0, metrics.invocations / 20.0)
        raw_score = (
            (adoption_rate * 40.0)
            + (success_rate * 30.0)
            + (reuse_breadth * 20.0)
            + (volume_factor * 10.0)
            - (retry_penalty * 100.0)
        )
        final_score = round(min(100.0, max(0.0, raw_score)), 2)

        # 4. Status determination
        status: SkillHealthStatus
        recommendation: str

        if final_score >= 80.0 and success_rate >= 0.90:
            status = SkillHealthStatus.STAR
            recommendation = "🌟 Star compounding asset! High adoption and zero friction across team."
        elif success_rate < 0.65 or retry_penalty >= 0.20:
            status = SkillHealthStatus.AT_RISK
            recommendation = "⚠️ At-risk asset. High failure/retry rate detected; review prompt and parameters."
        else:
            status = SkillHealthStatus.HEALTHY
            recommendation = "Healthy asset in active rotation."

        return SkillHealthScore(
            skill_id=metrics.skill_id,
            health_score=final_score,
            status=status,
            adoption_rate=round(adoption_rate, 4),
            success_rate=round(success_rate, 4),
            reuse_breadth=round(reuse_breadth, 4),
            actionable_recommendation=recommendation,
        )
