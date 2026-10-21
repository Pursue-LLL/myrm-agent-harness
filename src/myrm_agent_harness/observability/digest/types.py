"""Team Weekly Digest and Knowledge Compounding Type Definitions.

[INPUT]
- None (Standard library dataclasses, enum, datetime, typing)

[OUTPUT]
- SkillHealthStatus: Category enum (STAR, HEALTHY, AT_RISK, UNPROVEN)
- SkillCompoundingMetrics: Run counts and observed outcomes of a skill in the evaluation window
- SkillHealthScore: Evidence-weighted score and status of a skill
- MemberActivitySummary: Activity and token efficiency stats for a team member
- TeamWeeklyDigest: Complete aggregated weekly report contract

[POS]
Type definitions and data models for team weekly newsletter and knowledge compounding observability.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class SkillHealthStatus(StrEnum):
    """Categorical classification of skill health."""

    STAR = "STAR"  # Enough observed outcomes and almost all succeeded
    HEALTHY = "HEALTHY"  # Enough observed outcomes, acceptable success rate
    AT_RISK = "AT_RISK"  # Enough observed outcomes, frequent failures
    UNPROVEN = "UNPROVEN"  # Too few observed outcomes to judge quality


@dataclass(frozen=True, slots=True)
class SkillCompoundingMetrics:
    """Raw usage metrics for a skill over the evaluation period.

    Attributes:
        skill_id: Unique identifier or name of the skill.
        invocations: Runs in the period, including runs whose outcome was not observed.
        successful_invocations: Runs with an observed success.
        failed_invocations: Runs with an observed failure.
    """

    skill_id: str
    invocations: int = 0
    successful_invocations: int = 0
    failed_invocations: int = 0


@dataclass(frozen=True, slots=True)
class SkillHealthScore:
    """Evaluated health for a skill.

    Attributes:
        skill_id: Skill identifier.
        health_score: Success rate scaled by evidence, between 0.0 and 100.0.
        status: SkillHealthStatus classification.
        success_rate: Share of observed outcomes that succeeded; None when none was observed.
        actionable_recommendation: Diagnostic hint for maintaining or retiring the skill.
    """

    skill_id: str
    health_score: float
    status: SkillHealthStatus
    success_rate: float | None
    actionable_recommendation: str


@dataclass(frozen=True, slots=True)
class MemberActivitySummary:
    """Summary of AI Agent activity for a team member.

    Attributes:
        user_id: Unique member identifier or username.
        total_sessions: Total sessions initiated.
        total_steps: Total agent turns/steps executed.
        tokens_consumed: Total tokens used (prompt + completion).
        skills_created_or_refined: Number of skills authored/evolved.
        estimated_hours_saved: Estimated engineering hours saved.
    """

    user_id: str
    total_sessions: int = 0
    total_steps: int = 0
    tokens_consumed: int = 0
    skills_created_or_refined: int = 0
    estimated_hours_saved: float = 0.0


@dataclass(frozen=True, slots=True)
class TeamWeeklyDigest:
    """Complete aggregated team weekly digest report.

    Attributes:
        digest_id: Unique digest identifier.
        period_start: Start of the weekly reporting window.
        period_end: End of the weekly reporting window.
        team_name: Organization or squad name.
        total_active_members: Active users in the period.
        total_sessions: Total sessions across the team.
        total_tokens_consumed: Aggregate token usage.
        estimated_total_hours_saved: Aggregate engineering hours saved.
        star_skills: Top compounding skills.
        at_risk_skills: Fragile skills requiring maintenance.
        member_rankings: Top active members.
        top_friction_modules: High-friction modules / recurring obstacles.
        created_at: Digest generation timestamp.
    """

    period_start: datetime
    period_end: datetime
    team_name: str = "Engineering Team"
    total_active_members: int = 0
    total_sessions: int = 0
    total_tokens_consumed: int = 0
    estimated_total_hours_saved: float = 0.0
    star_skills: Sequence[SkillHealthScore] = field(default_factory=list)
    at_risk_skills: Sequence[SkillHealthScore] = field(default_factory=list)
    member_rankings: Sequence[MemberActivitySummary] = field(default_factory=list)
    top_friction_modules: Sequence[str] = field(default_factory=list)
    digest_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
