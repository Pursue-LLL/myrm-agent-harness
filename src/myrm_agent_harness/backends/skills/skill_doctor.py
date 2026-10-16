"""Skill library health diagnostics (the curator "doctor").

Reports anti-patterns the rule-based lifecycle sweep does not act on by itself: skills that run
often but fail, and pinned skills gone idle.

[INPUT]
- backends.skills.curator_config::CuratorConfig (POS: Skill curator configuration.)
- backends.skills.types::SkillMetadata (POS: Skill system core data types.)
- backends.skills.types::SkillLifecycleStatus (POS: Skill system core data types.)

[OUTPUT]
- SkillDoctorFinding: A diagnostic finding for one skill or the library as a whole.
- SkillHealthDiagnosis: Health report across the full skill library.
- evaluate_skill_health_findings: Build the health report from skills and a CuratorConfig.

[POS]
Skill library health diagnostics for the curator doctor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from myrm_agent_harness.backends.skills.curator_config import CuratorConfig
from myrm_agent_harness.backends.skills.types import SkillLifecycleStatus, SkillMetadata


@dataclass(slots=True)
class SkillDoctorFinding:
    """A diagnostic finding indicating an anti-pattern or health issue with a skill."""

    skill_name: str
    finding_type: str  # "wrong_but_frequent", "stale_pinned"
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
    2. STALE_PINNED: Pinned skills inactive for > stale_after_days.
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
                f"{'It is PINNED, exempting it from automatic archiving.' if stats.pinned else 'Degrading agent performance.'}"
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
                    details={"observed_count": stats.observed_count},
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
