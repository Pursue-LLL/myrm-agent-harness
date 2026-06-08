"""Skill forgetting / curator strategies to prevent skill accumulation.

Implements configurable strategies for identifying low-quality or stale skills
that should be transitioned through the lifecycle state machine
(active → stale → archived).

[INPUT]
- backends.skills.types::SkillMetadata (POS: Skill system core data types.)
- backends.skills.types::SkillUsageStats (POS: Skill system core data types.)
- backends.skills.types::SkillLifecycleStatus (POS: Skill system core data types.)
- backends.skills.types::SkillTrust (POS: Skill system core data types.)

[OUTPUT]
- CuratorConfig: Configuration for the skill curator / forgetting strategy.
- ForgettingConfig: Backward-compatible alias for CuratorConfig.
- ForgettingReason: Reason and target lifecycle state for a transition.
- ForgettingStrategy: Protocol for skill forgetting strategies.
- DefaultForgettingStrategy: Default strategy with pinned / grace / source checks.

[POS]
Skill forgetting / curator strategies to prevent skill accumulation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from myrm_agent_harness.backends.skills.types import (
    SkillLifecycleStatus,
    SkillMetadata,
    SkillTrust,
    SkillUsageStats,
)

logger = logging.getLogger(__name__)

_DEFAULT_STALE_DAYS = 30
_DEFAULT_ARCHIVE_DAYS = 90
_DEFAULT_MIN_SUCCESS_RATE = 0.3
_DEFAULT_MAX_SKILLS = 50
_DEFAULT_MIN_CALL_COUNT_FOR_QUALITY_CHECK = 5
_DEFAULT_GRACE_PERIOD_DAYS = 7
_DEFAULT_INTERVAL_HOURS = 168  # 7 days
_DEFAULT_CONSOLIDATION_MIN_SKILLS = 10
_DEFAULT_CONSOLIDATION_MIN_CLUSTER_SIZE = 3
_DEFAULT_CONSOLIDATION_SIMILARITY_THRESHOLD = 0.75


@dataclass(frozen=True, slots=True)
class CuratorConfig:
    """Configuration for the skill curator / forgetting strategy.

    Provides all knobs required by the curator engine and the forgetting
    strategy.  Every field has a sensible default so the curator works
    out-of-the-box without user configuration.
    """

    enabled: bool = True
    """Master switch.  Set to False to disable the curator entirely."""

    interval_hours: int = _DEFAULT_INTERVAL_HOURS
    """Minimum hours between curator runs (default 168 = 7 days)."""

    stale_after_days: int = _DEFAULT_STALE_DAYS
    """Days of inactivity before a skill is marked stale (default 30)."""

    archive_after_days: int = _DEFAULT_ARCHIVE_DAYS
    """Days of inactivity before a stale skill is archived (default 90)."""

    grace_period_days: int = _DEFAULT_GRACE_PERIOD_DAYS
    """Days after skill creation during which it is exempt from curator
    transitions (default 7).  Gives new skills time to accumulate usage."""

    min_success_rate: float = _DEFAULT_MIN_SUCCESS_RATE
    """Minimum success rate threshold (0.0-1.0).  Skills below this after
    min_call_count invocations may be considered low quality."""

    max_skills: int = _DEFAULT_MAX_SKILLS
    """Maximum number of active skills before LRU eviction kicks in."""

    min_call_count_for_quality_check: int = _DEFAULT_MIN_CALL_COUNT_FOR_QUALITY_CHECK
    """Minimum call count before evaluating success rate."""

    protect_installed_skills: bool = True
    """When True, skills with ``trust == INSTALLED`` (hub/registry) are
    exempt from curator transitions."""

    # --- Consolidation (Umbrella Merge) settings ---

    consolidation_enabled: bool = True
    """Enable skill consolidation (umbrella merge) during curator runs."""

    consolidation_min_skills: int = _DEFAULT_CONSOLIDATION_MIN_SKILLS
    """Minimum active skills before consolidation analysis is triggered."""

    consolidation_min_cluster_size: int = _DEFAULT_CONSOLIDATION_MIN_CLUSTER_SIZE
    """Minimum skills in a cluster to be considered for consolidation."""

    consolidation_similarity_threshold: float = _DEFAULT_CONSOLIDATION_SIMILARITY_THRESHOLD
    """Minimum embedding cosine similarity to group skills into a cluster."""

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "interval_hours": self.interval_hours,
            "stale_after_days": self.stale_after_days,
            "archive_after_days": self.archive_after_days,
            "grace_period_days": self.grace_period_days,
            "min_success_rate": self.min_success_rate,
            "max_skills": self.max_skills,
            "min_call_count_for_quality_check": self.min_call_count_for_quality_check,
            "protect_installed_skills": self.protect_installed_skills,
            "consolidation_enabled": self.consolidation_enabled,
            "consolidation_min_skills": self.consolidation_min_skills,
            "consolidation_min_cluster_size": self.consolidation_min_cluster_size,
            "consolidation_similarity_threshold": self.consolidation_similarity_threshold,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> CuratorConfig:
        if not data or not isinstance(data, dict):
            return cls()
        return cls(
            enabled=bool(data.get("enabled", True)),
            interval_hours=int(data.get("interval_hours", _DEFAULT_INTERVAL_HOURS)),
            stale_after_days=int(data.get("stale_after_days", _DEFAULT_STALE_DAYS)),
            archive_after_days=int(data.get("archive_after_days", _DEFAULT_ARCHIVE_DAYS)),
            grace_period_days=int(data.get("grace_period_days", _DEFAULT_GRACE_PERIOD_DAYS)),
            min_success_rate=float(data.get("min_success_rate", _DEFAULT_MIN_SUCCESS_RATE)),
            max_skills=int(data.get("max_skills", _DEFAULT_MAX_SKILLS)),
            min_call_count_for_quality_check=int(
                data.get("min_call_count_for_quality_check", _DEFAULT_MIN_CALL_COUNT_FOR_QUALITY_CHECK)
            ),
            protect_installed_skills=bool(data.get("protect_installed_skills", True)),
            consolidation_enabled=bool(data.get("consolidation_enabled", True)),
            consolidation_min_skills=int(data.get("consolidation_min_skills", _DEFAULT_CONSOLIDATION_MIN_SKILLS)),
            consolidation_min_cluster_size=int(
                data.get("consolidation_min_cluster_size", _DEFAULT_CONSOLIDATION_MIN_CLUSTER_SIZE)
            ),
            consolidation_similarity_threshold=float(
                data.get("consolidation_similarity_threshold", _DEFAULT_CONSOLIDATION_SIMILARITY_THRESHOLD)
            ),
        )


# Backward-compatible alias so existing code importing ForgettingConfig keeps working.
ForgettingConfig = CuratorConfig


@dataclass(frozen=True, slots=True)
class ForgettingReason:
    """Reason why a skill should transition to a new lifecycle state."""

    skill_name: str
    """Name of the skill"""

    reason_type: str
    """Reason type: stale, inactive, low_quality, lru_eviction"""

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

    def select_lru_candidates(
        self,
        skills: list[SkillMetadata],
    ) -> list[ForgettingReason]:
        """Select LRU eviction candidates when skill count exceeds max."""
        ...


class DefaultForgettingStrategy:
    """Default skill forgetting strategy with curator-aware checks.

    Evaluation order:
    1. Pinned / evolution-locked check — exempt from all automated transitions
    2. Source check — installed (hub/registry) skills optionally exempt
    3. Grace period — recently discovered skills are exempt (configurable days)
    4. Already archived — skip (terminal state for auto-transitions)
    5. Archive promotion — stale skill past archive threshold
    6. Stale check — inactivity or never-used
    7. Low quality — success rate below threshold

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

        # 2. Installed (hub/registry) skills optionally exempt
        if self._config.protect_installed_skills and skill.trust == SkillTrust.INSTALLED:
            return None

        # 3. Grace period — recently discovered skills are exempt
        if stats.created_at is not None:
            age_days = (datetime.now(UTC) - stats.created_at).days
            if age_days < self._config.grace_period_days:
                return None

        # 4. Already archived — no further auto-transitions
        if stats.lifecycle_status == SkillLifecycleStatus.ARCHIVED:
            return None

        # 5. Archive promotion: stale skill past archive threshold
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

        # 6. Stale check — never used or long inactive
        if stats.last_used_at is None and stats.call_count == 0:
            return ForgettingReason(
                skill_name=skill.name,
                reason_type="stale",
                reason_message=f"Never used (threshold: {self._config.stale_after_days} days)",
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

        # 7. Low quality check (only after sufficient usage)
        if (
            stats.call_count >= self._config.min_call_count_for_quality_check
            and stats.success_rate < self._config.min_success_rate
        ):
            return ForgettingReason(
                skill_name=skill.name,
                reason_type="low_quality",
                reason_message=(
                    f"Success rate {stats.success_rate:.1%} < "
                    f"{self._config.min_success_rate:.0%} "
                    f"(after {stats.call_count} calls)"
                ),
                stats=stats,
                target_status=SkillLifecycleStatus.STALE,
            )

        return None

    def select_lru_candidates(
        self,
        skills: list[SkillMetadata],
    ) -> list[ForgettingReason]:
        """Select LRU eviction candidates when skill count exceeds max.

        Only considers active, non-pinned, non-locked, non-grace-period skills.
        """
        now = datetime.now(UTC)
        eligible = [
            s
            for s in skills
            if not s.usage_stats.pinned
            and not s.evolution_locked
            and s.usage_stats.lifecycle_status == SkillLifecycleStatus.ACTIVE
            and not self._in_grace_period(s.usage_stats, now)
        ]

        if len(eligible) <= self._config.max_skills:
            return []

        sorted_skills = sorted(
            eligible,
            key=lambda s: s.usage_stats.last_used_at or datetime.min.replace(tzinfo=UTC),
        )

        evict_count = len(eligible) - self._config.max_skills
        candidates = sorted_skills[:evict_count]

        return [
            ForgettingReason(
                skill_name=skill.name,
                reason_type="lru_eviction",
                reason_message=(f"LRU eviction (active skill count {len(eligible)} > max {self._config.max_skills})"),
                stats=skill.usage_stats,
                target_status=SkillLifecycleStatus.STALE,
            )
            for skill in candidates
        ]

    def _in_grace_period(self, stats: SkillUsageStats, now: datetime) -> bool:
        """Check if a skill's stats indicate it's within the grace period."""
        if stats.created_at is None:
            return False
        return (now - stats.created_at).days < self._config.grace_period_days
