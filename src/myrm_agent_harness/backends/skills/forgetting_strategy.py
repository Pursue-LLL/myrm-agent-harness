"""Skill forgetting / curator strategies to prevent skill accumulation.

Implements configurable strategies for identifying low-quality or stale skills
that should be transitioned through the lifecycle state machine
(active → stale → archived).

[INPUT]
- backends.skills.curator_config::CuratorConfig (POS: Skill curator configuration.)
- backends.skills.types::SkillMetadata (POS: Skill system core data types.)
- backends.skills.types::SkillUsageStats (POS: Skill system core data types.)
- backends.skills.types::SkillLifecycleStatus (POS: Skill system core data types.)

[OUTPUT]
- ForgettingReason: Reason and target lifecycle state for a transition.
- ForgettingStrategy: Protocol for skill forgetting strategies.
- DefaultForgettingStrategy: Default strategy with pinned / grace / lifecycle checks.

[POS]
Skill forgetting / curator strategies to prevent skill accumulation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from myrm_agent_harness.backends.skills.curator_config import CuratorConfig
from myrm_agent_harness.backends.skills.types import (
    SkillLifecycleStatus,
    SkillMetadata,
    SkillUsageStats,
)


@dataclass(frozen=True, slots=True)
class ForgettingReason:
    """Reason why a skill should transition to a new lifecycle state."""

    skill_name: str
    """Name of the skill"""

    reason_type: str
    """Reason type: stale, inactive, low_quality, archive"""

    reason_message: str
    """Human-readable explanation"""

    stats: SkillUsageStats
    """Current usage statistics"""

    target_status: str = SkillLifecycleStatus.STALE
    """Target lifecycle status after this transition."""


class ForgettingStrategy(Protocol):
    """Protocol for skill forgetting strategies.

    Allows custom strategies to be plugged in by users.
    """

    def should_forget(self, skill: SkillMetadata) -> ForgettingReason | None:
        """Determine if a skill should transition to a new lifecycle state.

        Returns:
            ForgettingReason with target_status if the skill should transition,
            None otherwise.
        """
        ...


class DefaultForgettingStrategy:
    """Default skill forgetting strategy with curator-aware checks.

    Evaluation order:
    1. Pinned / evolution-locked check — exempt from all automated transitions
    2. Grace period — recently discovered skills are exempt (configurable days)
    3. Already archived — skip (terminal state for auto-transitions)
    4. Archive promotion — stale skill past archive threshold
    5. Stale check — inactivity or never-used
    6. Low quality — success rate below threshold

    Design:
    - Configurable thresholds via CuratorConfig
    - No database dependency
    - Framework-layer logic only
    """

    def __init__(self, config: CuratorConfig | None = None) -> None:
        self._config = config or CuratorConfig()

    @property
    def config(self) -> CuratorConfig:
        return self._config

    def should_forget(self, skill: SkillMetadata) -> ForgettingReason | None:
        """Check if a skill should transition lifecycle state."""
        stats = skill.usage_stats

        # 1. Pinned or evolution-locked skills are exempt from all automated transitions
        if stats.pinned or skill.evolution_locked:
            return None

        # 2. Grace period — recently discovered skills are exempt
        if stats.created_at is not None:
            age_days = (datetime.now(UTC) - stats.created_at).days
            if age_days < self._config.grace_period_days:
                return None

        # 3. Already archived — no further auto-transitions
        if stats.lifecycle_status == SkillLifecycleStatus.ARCHIVED:
            return None

        # 4. Archive promotion: stale skill past archive threshold
        if stats.lifecycle_status == SkillLifecycleStatus.STALE:
            reference_time = stats.last_used_at or stats.created_at
            if reference_time is not None:
                days_inactive = (datetime.now(UTC) - reference_time).days
                if days_inactive >= self._config.archive_after_days:
                    return ForgettingReason(
                        skill_name=skill.name,
                        reason_type="archive",
                        reason_message=(
                            f"Stale for {days_inactive} days (archive threshold: {self._config.archive_after_days})"
                        ),
                        stats=stats,
                        target_status=SkillLifecycleStatus.ARCHIVED,
                    )

        # 5. Stale check — never used past threshold, or long inactive
        if stats.last_used_at is None and stats.call_count == 0:
            reference_time = stats.created_at
            if reference_time is not None:
                age_days = (datetime.now(UTC) - reference_time).days
                if age_days >= self._config.stale_after_days:
                    return ForgettingReason(
                        skill_name=skill.name,
                        reason_type="stale",
                        reason_message=(
                            f"Never used for {age_days} days (stale threshold: {self._config.stale_after_days})"
                        ),
                        stats=stats,
                        target_status=SkillLifecycleStatus.STALE,
                    )

        if stats.last_used_at:
            days_inactive = (datetime.now(UTC) - stats.last_used_at).days
            if days_inactive >= self._config.stale_after_days:
                target = (
                    SkillLifecycleStatus.ARCHIVED
                    if days_inactive >= self._config.archive_after_days
                    else SkillLifecycleStatus.STALE
                )
                return ForgettingReason(
                    skill_name=skill.name,
                    reason_type="inactive",
                    reason_message=(
                        f"Not used for {days_inactive} days "
                        f"(stale: {self._config.stale_after_days}, "
                        f"archive: {self._config.archive_after_days})"
                    ),
                    stats=stats,
                    target_status=target,
                )

        # 6. Low quality check (only after enough runs with an observed outcome)
        if (
            stats.observed_count >= self._config.min_call_count_for_quality_check
            and stats.success_rate < self._config.min_success_rate
        ):
            return ForgettingReason(
                skill_name=skill.name,
                reason_type="low_quality",
                reason_message=(
                    f"Success rate {stats.success_rate:.1%} < "
                    f"{self._config.min_success_rate:.0%} "
                    f"(after {stats.observed_count} observed runs)"
                ),
                stats=stats,
                target_status=SkillLifecycleStatus.STALE,
            )

        return None
