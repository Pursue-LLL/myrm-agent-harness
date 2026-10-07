"""[POS]: src/myrm_agent_harness/toolkits/memory/job_compounding/maturity_tracker.py
[INPUT]: JobDescriptionSpec and accumulated CompoundedRule collections.
[OUTPUT]: CompoundingMaturityTracker assessing score, growth tier, and detailed maturity reports.
"""

from __future__ import annotations

from .models import (
    CompoundedRule,
    CompoundingMaturityReport,
    JobDescriptionSpec,
    MaturityTier,
    RuleType,
)


class CompoundingMaturityTracker:
    """Evaluates the maturity progression, rule coverage, and operational compounding tier of an agent."""

    @classmethod
    def calculate_score(cls, rules: list[CompoundedRule]) -> float:
        """Calculates compounding maturity score between 0.0 and 100.0 based on rule depth and variety."""
        if not rules:
            return 0.0

        # 1. Volume Score (Up to 40 points): capped at 20 rules
        volume_score = min(40.0, len(rules) * 2.0)

        # 2. Diversity Score (Up to 30 points): 10 points per represented rule type
        present_types = {r.rule_type for r in rules}
        diversity_score = len(present_types) * 10.0

        # 3. Usage & Adoption Score (Up to 30 points): based on cumulative rule hits
        total_hits = sum(r.hit_count for r in rules)
        usage_score = min(30.0, total_hits * 1.5)

        total = volume_score + diversity_score + usage_score
        return round(min(100.0, total), 1)

    @classmethod
    def determine_tier(cls, score: float) -> MaturityTier:
        """Maps quantitative score to developmental role maturity tier."""
        if score >= 80.0:
            return MaturityTier.PARTNER
        if score >= 50.0:
            return MaturityTier.SPECIALIST
        if score >= 25.0:
            return MaturityTier.PRACTITIONER
        return MaturityTier.ROOKIE

    @classmethod
    def evaluate_maturity(
        cls,
        spec: JobDescriptionSpec,
        rules: list[CompoundedRule],
    ) -> CompoundingMaturityReport:
        """Generates comprehensive compounding health report for the given agent."""
        positives = sum(1 for r in rules if r.rule_type == RuleType.POSITIVE_PREFERENCE)
        negatives = sum(1 for r in rules if r.rule_type == RuleType.NEGATIVE_CONSTRAINT)
        lessons = sum(1 for r in rules if r.rule_type == RuleType.INSPECTION_LESSON)

        score = cls.calculate_score(rules)
        tier = cls.determine_tier(score)

        tier_summary_map = {
            MaturityTier.ROOKIE: (
                f"Agent {spec.job_title} is at Rookie stage with baseline configuration. "
                "Requires more user corrections and feedback iterations to build compounding domain memory."
            ),
            MaturityTier.PRACTITIONER: (
                f"Agent {spec.job_title} has reached Practitioner stage with structured domain preferences. "
                "Can reliably avoid common pitfalls and follows basic working styles."
            ),
            MaturityTier.SPECIALIST: (
                f"Agent {spec.job_title} has achieved Specialist tier with rich domain lessons and constraints. "
                "Operates with high autonomy inside approval boundaries."
            ),
            MaturityTier.PARTNER: (
                f"Agent {spec.job_title} has reached Partner status! High domain compounding maturity, "
                "deeply aligned with user preferences and team operational procedures."
            ),
        }

        return CompoundingMaturityReport(
            agent_id=spec.agent_id,
            job_title=spec.job_title,
            total_rules_count=len(rules),
            positive_preferences_count=positives,
            negative_constraints_count=negatives,
            inspection_lessons_count=lessons,
            maturity_score=score,
            tier=tier,
            summary=tier_summary_map[tier],
        )
