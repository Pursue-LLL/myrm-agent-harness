"""A/B Test Engine

1. INPUT/OUTPUT/POS annotations

[INPUT]
- .types::ABTestResult, ABTestStatus, SkillQualityScore, VersionConflictError (POS: A/B test types)
- .config::ABTestConfig (POS: A/B test configuration)

[OUTPUT]
- ABTestEngine: A/B test engine (adaptive sampling + quick failure detection + early stopping)

[POS]
A/B test engine. Implements scientific optimization validation with traffic splitting and statistical significance testing.

"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import ABTestConfig
    from .types import ABTestResult, SkillQualityScore

from .types import ABTestStatus, VersionConflictError

logger = logging.getLogger(__name__)


class ABTestEngine:
    """A/B test engine with adaptive sampling and statistical validation.

    Strategies:
    1. Adaptive sampling: dynamically adjusts sample size based on skill call frequency
    2. Quick failure detection: stops early when candidate is significantly worse
    3. Early stopping: stops early when candidate is significantly better
    4. Statistical significance: uses t-test to ensure reliable results
    5. Version conflict detection: optimistic locking to prevent concurrent modifications
    """

    def __init__(self, config: ABTestConfig):
        self.config = config

    async def start_ab_test(
        self,
        skill_id: str,
        baseline_version: int,
        baseline_score: SkillQualityScore,
        candidate_content: str,
        current_skill_version: int | None = None,
    ) -> ABTestResult:
        """Start an A/B test for a skill optimization candidate.

        Args:
            skill_id: Skill ID
            baseline_version: Baseline version number
            baseline_score: Baseline quality score
            candidate_content: Candidate version content
            current_skill_version: Current skill version for optimistic lock check

        Returns:
            ABTestResult with RUNNING status

        Raises:
            VersionConflictError: if skill was modified during optimization
        """
        from .types import ABTestResult

        started_at = datetime.now()

        logger.info(
            "Starting A/B test for skill: %s, baseline_version: %d",
            skill_id,
            baseline_version,
        )

        if current_skill_version is not None and current_skill_version != baseline_version:
            raise VersionConflictError(
                f"Skill version changed during optimization: expected {baseline_version}, got {current_skill_version}"
            )

        target_sample_size = self._calculate_sample_size(baseline_score.call_frequency)

        result = ABTestResult(
            skill_id=skill_id,
            baseline_version=baseline_version,
            candidate_version=baseline_version + 1,
            baseline_score=baseline_score,
            candidate_score=baseline_score,
            sample_size=0,
            status=ABTestStatus.RUNNING,
            started_at=started_at,
        )

        logger.info(
            "A/B test started: %s, target_sample_size=%d, baseline_score=%.2f",
            skill_id,
            target_sample_size,
            baseline_score.overall_score,
        )

        return result

    async def evaluate_ab_test(self, ab_test: ABTestResult, candidate_samples: list[dict]) -> ABTestResult:
        """Evaluate A/B test results after collecting samples.

        Args:
            ab_test: A/B test record
            candidate_samples: Execution sample data for the candidate version

        Returns:
            Updated ABTestResult with winner decision if enough samples collected
        """
        candidate_score = self._calculate_quality_score(candidate_samples)
        ab_test.candidate_score = candidate_score
        ab_test.sample_size = len(candidate_samples)

        should_stop, stop_reason = self._should_stop_early(ab_test.baseline_score, candidate_score, ab_test.sample_size)

        if should_stop:
            if stop_reason == "quick_failure":
                ab_test.status = ABTestStatus.BASELINE_WIN
                ab_test.winner = "baseline"
                logger.warning("A/B test quick failure: %s, rolling back", ab_test.skill_id)
            elif stop_reason == "early_stopping":
                ab_test.status = ABTestStatus.CANDIDATE_WIN
                ab_test.winner = "candidate"
                logger.info("A/B test early stopping: %s, candidate wins", ab_test.skill_id)

            ab_test.completed_at = datetime.now()
            return ab_test

        target_sample_size = self._calculate_sample_size(ab_test.baseline_score.call_frequency)
        if ab_test.sample_size >= target_sample_size:
            is_significant = self._is_statistically_significant(
                ab_test.baseline_score, candidate_score, ab_test.sample_size
            )

            if not is_significant:
                ab_test.status = ABTestStatus.NO_DIFFERENCE
                ab_test.winner = "baseline"
                logger.info("A/B test no significant difference: %s", ab_test.skill_id)
            elif candidate_score.overall_score > ab_test.baseline_score.overall_score:
                ab_test.status = ABTestStatus.CANDIDATE_WIN
                ab_test.winner = "candidate"
                logger.info("A/B test completed: %s, candidate wins", ab_test.skill_id)
            else:
                ab_test.status = ABTestStatus.BASELINE_WIN
                ab_test.winner = "baseline"
                logger.info("A/B test completed: %s, baseline wins", ab_test.skill_id)

            ab_test.completed_at = datetime.now()

        return ab_test

    def _calculate_quality_score(self, samples: list[dict]) -> SkillQualityScore:
        """Compute quality score from execution samples.

        Each sample dict may contain: success (bool), tokens_used (int),
        execution_time (float), user_feedback (int: -1/0/1).
        """
        from .types import SkillQualityScore

        if not samples:
            return SkillQualityScore(
                success_rate=0.0, token_efficiency=0.0, execution_time=0.0, user_satisfaction=0.5, call_frequency=0.0
            )

        success_count = sum(1 for s in samples if s.get("success", False))
        success_rate = success_count / len(samples)

        avg_tokens = sum(s.get("tokens_used", 0) for s in samples) / len(samples)
        token_efficiency = max(0, min(1, 1000 / (avg_tokens + 1)))

        avg_time = sum(s.get("execution_time", 0) for s in samples) / len(samples)
        execution_time = max(0, min(1, 10 / (avg_time + 0.1)))

        feedbacks = [s.get("user_feedback", 0) for s in samples if "user_feedback" in s]
        if feedbacks:
            avg_feedback = sum(feedbacks) / len(feedbacks)
            user_satisfaction = (avg_feedback + 1) / 2
        else:
            user_satisfaction = 0.5

        call_frequency = 0.5

        return SkillQualityScore(
            success_rate=success_rate,
            token_efficiency=token_efficiency,
            execution_time=execution_time,
            user_satisfaction=user_satisfaction,
            call_frequency=call_frequency,
        )

    def _calculate_sample_size(self, call_frequency: float) -> int:
        """Calculate adaptive sample size via linear interpolation between
        min and max based on call frequency (0-1 normalized)."""
        if not self.config.enable_adaptive_sampling:
            return self.config.max_sample_size

        sample_size = int(
            self.config.min_sample_size + (self.config.max_sample_size - self.config.min_sample_size) * call_frequency
        )

        return sample_size

    def _should_stop_early(
        self, baseline_score: SkillQualityScore, candidate_score: SkillQualityScore, current_sample_size: int
    ) -> tuple[bool, str]:
        """Determine whether to stop the test early.

        Returns (should_stop, reason) where reason is 'quick_failure'
        or 'early_stopping'.
        """
        score_diff = candidate_score.overall_score - baseline_score.overall_score

        if (
            self.config.enable_quick_failure_detection
            and score_diff < -self.config.quick_failure_threshold
            and current_sample_size >= self.config.min_sample_size
        ):
            return (True, "quick_failure")

        if (
            self.config.enable_early_stopping
            and score_diff > self.config.early_stopping_threshold
            and current_sample_size >= self.config.min_sample_size
        ):
            return (True, "early_stopping")

        return (False, "")

    def _is_statistically_significant(
        self, baseline_score: SkillQualityScore, candidate_score: SkillQualityScore, sample_size: int
    ) -> bool:
        """Simplified statistical significance check using effect size
        and confidence-adjusted threshold (Cohen's d approximation)."""
        if sample_size < self.config.min_sample_size:
            return False

        score_diff = abs(candidate_score.overall_score - baseline_score.overall_score)

        if score_diff < self.config.min_effect_size:
            return False

        confidence_multiplier = self.config.confidence_level
        adjusted_threshold = self.config.min_effect_size * (2 - confidence_multiplier)

        return score_diff >= adjusted_threshold

    def _is_statistically_significant_with_samples(
        self, baseline_samples: list[float], candidate_samples: list[float]
    ) -> bool:
        """Full statistical significance test using independent-samples t-test
        when raw sample data is available. Falls back to effect-size check
        if scipy is not installed."""
        try:
            from scipy import stats

            if len(baseline_samples) < 2 or len(candidate_samples) < 2:
                return False

            _t_statistic, p_value = stats.ttest_ind(baseline_samples, candidate_samples)

            alpha = 1 - self.config.confidence_level

            return p_value < alpha

        except (ImportError, TypeError):
            logger.warning("scipy not available, using simplified significance test")
            import statistics

            baseline_mean = statistics.mean(baseline_samples)
            candidate_mean = statistics.mean(candidate_samples)
            score_diff = abs(candidate_mean - baseline_mean)

            return score_diff >= self.config.min_effect_size
