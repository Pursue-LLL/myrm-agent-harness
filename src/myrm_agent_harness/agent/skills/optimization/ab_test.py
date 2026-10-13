"""A/B Test Engine

1. INPUT/OUTPUT/POS annotations

[INPUT]
- .types::ABTestResult, ABTestStatus, SkillQualityScore, VersionConflictError (POS: A/B test types)
- .config::ABTestConfig (POS: A/B test configuration)

[OUTPUT]
- ABTestEngine: starts A/B tests for optimization candidates (adaptive target sample size + optimistic version lock)

[POS]
A/B test starter. Creates the RUNNING ABTestResult for a candidate version; collecting samples and deciding the winner is owned by the host application.

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
    """A/B test engine with adaptive sampling and version conflict detection.

    Strategies:
    1. Adaptive sampling: scales the target sample size with the skill call frequency
    2. Version conflict detection: optimistic locking to prevent concurrent modifications
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

    def _calculate_sample_size(self, call_frequency: float) -> int:
        """Calculate adaptive sample size via linear interpolation between
        min and max based on call frequency (0-1 normalized)."""
        if not self.config.enable_adaptive_sampling:
            return self.config.max_sample_size

        sample_size = int(
            self.config.min_sample_size + (self.config.max_sample_size - self.config.min_sample_size) * call_frequency
        )

        return sample_size
