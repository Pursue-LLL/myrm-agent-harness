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
- DefaultForgettingStrategy: Default strategy with pinned / grace / source checks.
- SkillDoctorFinding: A diagnostic finding for one skill or the library as a whole.
- SkillHealthDiagnosis: Health report across the full skill library.
- evaluate_skill_health_findings: Build the health report from skills and a CuratorConfig.

[POS]
Skill forgetting / curator strategies to prevent skill accumulation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    2. Source check — prebuilt/system skills optionally exempt
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

        # 2. Prebuilt/system skills optionally exempt
        if self._config.protect_system_skills and skill.storage_path:
            normalized = skill.storage_path.replace("\\", "/")
            if "/prebuilt/" in normalized:
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

        # 6. Stale check — never used past threshold, or long inactive
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

        # 7. Low quality check (only after enough runs with an observed outcome)
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


@dataclass(slots=True)
class SkillDoctorFinding:
    """A diagnostic finding indicating an anti-pattern or health issue with a skill."""

    skill_name: str
    finding_type: str  # "wrong_but_frequent", "hoarding_bloat", "stale_pinned"
    severity: str  # "critical", "warning", "info"
    message: str
    call_count: int
    success_rate: float
    pinned: bool
    recommended_action: str  # "unpin_and_archive", "archive", "reset_stats", "evolve"
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "skill_name": self.skill_name,
            "finding_type": self.finding_type,
            "severity": self.severity,
            "message": self.message,
            "call_count": self.call_count,
            "success_rate": round(self.success_rate, 4),
            "pinned": self.pinned,
            "recommended_action": self.recommended_action,
            "details": self.details,
        }


@dataclass(slots=True)
class SkillHealthDiagnosis:
    """Comprehensive health diagnostic report across the full skill library."""

    total_skills: int
    active_skills: int
    stale_skills: int
    archived_skills: int
    pinned_skills: int
    findings: list[SkillDoctorFinding] = field(default_factory=list)
    health_score: float = 100.0

    def to_dict(self) -> dict[str, object]:
        return {
            "total_skills": self.total_skills,
            "active_skills": self.active_skills,
            "stale_skills": self.stale_skills,
            "archived_skills": self.archived_skills,
            "pinned_skills": self.pinned_skills,
            "findings": [f.to_dict() for f in self.findings],
            "health_score": round(self.health_score, 1),
        }


def evaluate_skill_health_findings(
    skills: list[SkillMetadata],
    config: CuratorConfig | None = None,
) -> SkillHealthDiagnosis:
    """Evaluate skill library health and generate actionable Doctor Findings.

    Detects:
    1. WRONG_BUT_FREQUENT: Enough observed run outcomes (>= min_call_count) with low success rate (< min_success_rate),
       especially when pinned or installed, which bypasses normal forgetting.
    2. HOARDING_BLOAT: Active skill count exceeding threshold or large clusters of unpruned skills.
    3. STALE_PINNED: Pinned skills inactive for > stale_after_days.
    """
    cfg = config or CuratorConfig()
    now = datetime.now(UTC)

    total = len(skills)
    active = 0
    stale = 0
    archived = 0
    pinned_count = 0
    findings: list[SkillDoctorFinding] = []

    for skill in skills:
        stats = skill.usage_stats
        status = stats.lifecycle_status
        if status == SkillLifecycleStatus.ACTIVE:
            active += 1
        elif status == SkillLifecycleStatus.STALE:
            stale += 1
        elif status == SkillLifecycleStatus.ARCHIVED:
            archived += 1

        if stats.pinned:
            pinned_count += 1

        # Check 1: Wrong but frequent (Hermes Failure Mode #142)
        if stats.observed_count >= cfg.min_call_count_for_quality_check and stats.success_rate < cfg.min_success_rate:
            severity = "critical" if stats.success_rate < 0.15 else "warning"
            action = "unpin_and_archive" if stats.pinned else "archive"
            msg = (
                f"Skill '{skill.name}' ran {stats.observed_count} times with an observed outcome but has low success rate "
                f"({stats.success_rate:.1%}). "
                f"{'It is PINNED, exempting it from automatic LRU eviction.' if stats.pinned else 'Degrading agent performance.'}"
            )
            findings.append(
                SkillDoctorFinding(
                    skill_name=skill.name,
                    finding_type="wrong_but_frequent",
                    severity=severity,
                    message=msg,
                    call_count=stats.call_count,
                    success_rate=stats.success_rate,
                    pinned=stats.pinned,
                    recommended_action=action,
                    details={
                        "observed_count": stats.observed_count,
                        "success_count": stats.success_count,
                        "failure_count": stats.failure_count,
                        "trust": skill.trust.name.lower(),
                    },
                )
            )

        # Check 2: Stale pinned skills (pinned but not used for a long time)
        elif stats.pinned and stats.last_used_at:
            days_inactive = (now - stats.last_used_at).days
            if days_inactive >= cfg.stale_after_days:
                findings.append(
                    SkillDoctorFinding(
                        skill_name=skill.name,
                        finding_type="stale_pinned",
                        severity="info",
                        message=f"Pinned skill '{skill.name}' unused for {days_inactive} days.",
                        call_count=stats.call_count,
                        success_rate=stats.success_rate,
                        pinned=True,
                        recommended_action="unpin_and_archive",
                        details={"days_inactive": days_inactive},
                    )
                )

    # Check 3: Hoarding / Library bloat
    if active > cfg.max_skills:
        excess = active - cfg.max_skills
        findings.append(
            SkillDoctorFinding(
                skill_name="[Library Bloat]",
                finding_type="hoarding_bloat",
                severity="warning",
                message=f"Active skills ({active}) exceed target limit ({cfg.max_skills}) by {excess}.",
                call_count=0,
                success_rate=1.0,
                pinned=False,
                recommended_action="archive",
                details={
                    "active_count": active,
                    "max_skills": cfg.max_skills,
                    "excess": excess,
                },
            )
        )

    # Calculate overall health score (100 base, deductions for findings)
    score = 100.0
    for f in findings:
        if f.severity == "critical":
            score -= 25.0
        elif f.severity == "warning":
            score -= 15.0
        elif f.severity == "info":
            score -= 5.0
    score = max(0.0, min(100.0, score))

    return SkillHealthDiagnosis(
        total_skills=total,
        active_skills=active,
        stale_skills=stale,
        archived_skills=archived,
        pinned_skills=pinned_count,
        findings=findings,
        health_score=score,
    )
