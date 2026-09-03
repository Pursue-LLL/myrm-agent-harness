"""Team Weekly Digest and Knowledge Compounding Type Definitions.

[INPUT]
- None (Standard library dataclasses, enum, datetime, typing)

[OUTPUT]
- SkillHealthStatus: Category enum (STAR, HEALTHY, AT_RISK, STALE)
- SkillCompoundingMetrics: Raw usage and feedback metrics for a skill
- SkillHealthScore: Multi-dimensional score and classification for a skill
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
    """Categorical classification of skill health and compounding value."""

    STAR = "STAR"          # High adoption, zero error, frequent reuse
    HEALTHY = "HEALTHY"    # Regular usage, low error rate
    AT_RISK = "AT_RISK"    # High retry rate, frequent execution failures
    STALE = "STALE"        # Dormant, not invoked in last 30 days


@dataclass(frozen=True, slots=True)
class SkillCompoundingMetrics:
    """Raw usage metrics for a skill over the evaluation period.

    Attributes:
        skill_id: Unique identifier or name of the skill.
        invocations: Total execution count.
        successful_invocations: Successful executions without exceptions.
        adopted_outputs: Outputs accepted/applied by human or agent turns.
        retry_count: Number of immediate fix-and-retry loops caused by errors.
        distinct_sessions: Number of unique sessions using this skill.
        last_invoked_at: Timestamp of the most recent invocation.
    """

    skill_id: str
    invocations: int = 0
    successful_invocations: int = 0
    adopted_outputs: int = 0
    retry_count: int = 0
    distinct_sessions: int = 0
    last_invoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SkillHealthScore:
    """Evaluated health and compounding index for a skill.

    Attributes:
        skill_id: Skill identifier.
        health_score: Composite score between 0.0 and 100.0.
        status: SkillHealthStatus classification.
        adoption_rate: Ratio of adopted outputs to total invocations.
        success_rate: Ratio of successful invocations to total invocations.
        reuse_breadth: Ratio of distinct sessions to total invocations.
        actionable_recommendation: Diagnostic hint for maintaining or retiring the skill.
    """

    skill_id: str
    health_score: float
    status: SkillHealthStatus
    adoption_rate: float
    success_rate: float
    reuse_breadth: float
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
