"""Unit tests for Harness SkillHealthEvaluator and digest types."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.observability.digest.health_evaluator import (
    SkillHealthEvaluator,
)
from myrm_agent_harness.observability.digest.types import (
    SkillCompoundingMetrics,
    SkillHealthStatus,
)

MIN_OBSERVED = 5


def _metrics(
    *,
    succeeded: int,
    failed: int = 0,
    unobserved: int = 0,
    last_invoked_at: datetime | None = None,
) -> SkillCompoundingMetrics:
    return SkillCompoundingMetrics(
        skill_id="demo",
        invocations=succeeded + failed + unobserved,
        successful_invocations=succeeded,
        failed_invocations=failed,
        last_invoked_at=last_invoked_at or datetime.now(UTC),
    )


def test_dormant_skill_zero_invocations() -> None:
    """A skill with 0 invocations is STALE with a 0 score and no success rate."""
    metrics = SkillCompoundingMetrics(skill_id="legacy-script")

    score = SkillHealthEvaluator.evaluate(metrics, min_observed=MIN_OBSERVED)

    assert score.skill_id == "legacy-script"
    assert score.health_score == 0.0
    assert score.status == SkillHealthStatus.STALE
    assert score.success_rate is None
    assert "not been invoked" in score.actionable_recommendation


def test_stale_skill_inactive_over_threshold() -> None:
    """A skill inactive for more than the threshold is STALE and keeps its observed rate."""
    now = datetime.now(UTC)
    metrics = _metrics(succeeded=8, failed=2, last_invoked_at=now - timedelta(days=45))

    score = SkillHealthEvaluator.evaluate(
        metrics, min_observed=MIN_OBSERVED, reference_time=now, stale_days_threshold=30
    )

    assert score.health_score == 15.0
    assert score.status == SkillHealthStatus.STALE
    assert score.success_rate == 0.8
    assert "Inactive for 45 days" in score.actionable_recommendation


def test_reliable_skill_with_enough_outcomes_is_star() -> None:
    score = SkillHealthEvaluator.evaluate(_metrics(succeeded=25), min_observed=MIN_OBSERVED)

    assert score.status == SkillHealthStatus.STAR
    assert score.health_score == 100.0
    assert "Star asset" in score.actionable_recommendation


def test_failing_skill_with_enough_outcomes_is_at_risk() -> None:
    score = SkillHealthEvaluator.evaluate(_metrics(succeeded=10, failed=10), min_observed=MIN_OBSERVED)

    assert score.status == SkillHealthStatus.AT_RISK
    assert score.success_rate == 0.5
    assert "At-risk asset" in score.actionable_recommendation


def test_acceptable_skill_with_enough_outcomes_is_healthy() -> None:
    score = SkillHealthEvaluator.evaluate(_metrics(succeeded=8, failed=2), min_observed=MIN_OBSERVED)

    assert score.status == SkillHealthStatus.HEALTHY
    assert score.health_score == 80.0
    assert "Healthy asset in active rotation" in score.actionable_recommendation


@pytest.mark.parametrize("outcome", ["succeeded", "failed"])
def test_too_few_outcomes_is_unproven_whatever_they_say(outcome: str) -> None:
    """One lucky or unlucky run is neither a star nor at risk."""
    metrics = _metrics(succeeded=1) if outcome == "succeeded" else _metrics(succeeded=0, failed=1)

    score = SkillHealthEvaluator.evaluate(metrics, min_observed=MIN_OBSERVED)

    assert score.status == SkillHealthStatus.UNPROVEN
    assert "1 of 5" in score.actionable_recommendation


def test_runs_without_an_observed_outcome_are_not_evidence() -> None:
    """Unobserved runs neither raise nor lower the score; they only show the skill is used."""
    score = SkillHealthEvaluator.evaluate(_metrics(succeeded=0, unobserved=30), min_observed=MIN_OBSERVED)

    assert score.status == SkillHealthStatus.UNPROVEN
    assert score.health_score == 0.0
    assert score.success_rate is None


def test_score_never_drops_as_an_all_success_skill_gains_runs() -> None:
    """More successful evidence must never lower the score or demote the status."""
    scores = [
        SkillHealthEvaluator.evaluate(_metrics(succeeded=runs), min_observed=MIN_OBSERVED) for runs in range(1, 101)
    ]

    values = [score.health_score for score in scores]
    assert values == sorted(values)
    assert [score.status for score in scores[: MIN_OBSERVED - 1]] == [SkillHealthStatus.UNPROVEN] * (MIN_OBSERVED - 1)
    assert {score.status for score in scores[MIN_OBSERVED - 1 :]} == {SkillHealthStatus.STAR}


def test_min_observed_is_honored_exactly_at_the_boundary() -> None:
    below = SkillHealthEvaluator.evaluate(_metrics(succeeded=4), min_observed=5)
    at = SkillHealthEvaluator.evaluate(_metrics(succeeded=5), min_observed=5)

    assert below.status == SkillHealthStatus.UNPROVEN
    assert at.status == SkillHealthStatus.STAR
