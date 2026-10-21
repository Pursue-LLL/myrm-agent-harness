"""
[INPUT]: Multi-agent runtime execution events, user activity telemetry, and period query configurations.
[OUTPUT]: Pydantic domain models for cross-period comparative pivot reports, team adoption insights, and gamified competency milestones.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/cross_period_milestone/models.py
"""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class PeriodType(str, Enum):
    """Reporting timeframe granularity for multi-agent analytics."""

    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    CUSTOM = "custom"


class AgentRuntimeUsagePoint(BaseModel):
    """Runtime resource consumption and operational metrics for a specific agent persona."""

    agent_id: str = Field(..., description="Unique agent identifier (e.g. workbuddy, hermes, coding_agent)")
    agent_name: str = Field(..., description="Human-readable agent display name")
    tokens_in: int = Field(default=0, ge=0, description="Prompt / input tokens consumed")
    tokens_out: int = Field(default=0, ge=0, description="Completion / generated tokens")
    total_tokens: int = Field(default=0, ge=0, description="Aggregated total token consumption")
    token_share_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Percentage share of total period tokens")
    cost_usd: float = Field(default=0.0, ge=0.0, description="Financial cost incurred in USD")
    invocation_count: int = Field(default=0, ge=0, description="Number of task/run invocations")
    success_rate: float = Field(default=1.0, ge=0.0, le=1.0, description="Ratio of successful invocations")
    avg_latency_ms: float = Field(default=0.0, ge=0.0, description="Average response latency in milliseconds")


class PeriodAggregateSummary(BaseModel):
    """Aggregated multi-agent operational metrics for a discrete timeframe."""

    period_type: PeriodType = Field(..., description="Type of reporting period")
    period_label: str = Field(..., description="Human-readable label, e.g. '2026-W41', '2026-10', '2026-Q4'")
    start_date: str = Field(..., description="ISO formatted start date string YYYY-MM-DD")
    end_date: str = Field(..., description="ISO formatted end date string YYYY-MM-DD")
    total_tokens: int = Field(default=0, ge=0, description="Total tokens consumed across all agents")
    total_cost_usd: float = Field(default=0.0, ge=0.0, description="Total cost incurred across all agents")
    total_invocations: int = Field(default=0, ge=0, description="Total task executions executed")
    agent_breakdowns: List[AgentRuntimeUsagePoint] = Field(
        default_factory=list, description="Per-agent stacked runtime usage points"
    )


class CrossPeriodPivotReport(BaseModel):
    """Comparative pivot analysis comparing the current period against the preceding period."""

    current_period: PeriodAggregateSummary = Field(..., description="Current active period summary")
    previous_period: Optional[PeriodAggregateSummary] = Field(
        default=None, description="Immediately preceding equal-length period summary if available"
    )
    token_growth_pct: Optional[float] = Field(
        default=None, description="Percentage change in token volume relative to previous period"
    )
    cost_growth_pct: Optional[float] = Field(
        default=None, description="Percentage change in cost relative to previous period"
    )
    invocation_growth_pct: Optional[float] = Field(
        default=None, description="Percentage change in invocations relative to previous period"
    )


class DailyEfficiencyTask(BaseModel):
    """Gamified daily mission encouraging employees to adopt AI superpowers."""

    id: str = Field(..., description="Unique task identifier")
    title: str = Field(..., description="Task title (e.g. 'Delegate Code Review to Agent')")
    description: str = Field(..., description="Detailed instructions on achieving this task")
    xp_reward: int = Field(default=50, ge=1, description="Experience points rewarded upon completion")
    is_completed: bool = Field(default=False, description="Whether task has been completed today")
    progress: int = Field(default=0, ge=0, description="Current achieved progress count")
    max_progress: int = Field(default=1, ge=1, description="Target goal count")


class MilestoneBadge(BaseModel):
    """Recognized competency badge awarded to user upon reaching efficiency milestones."""

    id: str = Field(..., description="Badge identifier (e.g. 'prompt_architect', 'multi_agent_commander')")
    name: str = Field(..., description="Display title of the badge")
    description: str = Field(..., description="Achievement criteria requirement")
    tier: str = Field(..., description="bronze | silver | gold | platinum")
    icon: str = Field(default="award", description="Icon designator")
    is_unlocked: bool = Field(default=False, description="Whether currently unlocked by the user")
    unlocked_at: Optional[str] = Field(default=None, description="ISO timestamp of unlock event")


class UserGamifiedProfile(BaseModel):
    """User-centric competency progression profile, level, streak, and daily quests."""

    user_id: str = Field(..., description="Unique user identifier")
    user_name: str = Field(..., description="User display name")
    level: int = Field(default=1, ge=1, description="Current competency level (1~100)")
    rank_title: str = Field(default="AI 协同新手", description="Title corresponding to level tier")
    current_xp: int = Field(default=0, ge=0, description="Accumulated experience points in current level")
    next_level_xp: int = Field(default=500, ge=1, description="Required experience points to reach next level")
    total_xp: int = Field(default=0, ge=0, description="All-time lifetime accumulated experience points")
    streak_days: int = Field(default=1, ge=0, description="Consecutive active days with AI collaboration")
    daily_tasks: List[DailyEfficiencyTask] = Field(default_factory=list, description="Today's actionable missions")
    badges: List[MilestoneBadge] = Field(default_factory=list, description="Earned and pending competency badges")


class TeamMemberAdoptionItem(BaseModel):
    """Individual team member adoption snapshot for leaderboard insight."""

    user_id: str = Field(..., description="Unique user identifier")
    user_name: str = Field(..., description="User display name")
    department: str = Field(default="Engineering", description="User department or business unit")
    streak_days: int = Field(default=1, ge=0, description="Consecutive active days")
    sessions_count: int = Field(default=0, ge=0, description="Total sessions initiated")
    total_tokens: int = Field(default=0, ge=0, description="Total tokens leveraged")
    level: int = Field(default=1, ge=1, description="Current user level")
    rank_title: str = Field(default="AI 协同新手", description="Rank title")


class TeamAdoptionInsights(BaseModel):
    """Team-level AI adoption and organizational velocity insights."""

    total_active_members: int = Field(default=0, ge=0, description="Count of team members adopting Agents")
    average_streak_days: float = Field(default=0.0, ge=0.0, description="Average consecutive active days")
    total_team_sessions: int = Field(default=0, ge=0, description="Aggregate team collaborative sessions")
    top_task_categories: List[Dict[str, str]] = Field(
        default_factory=list, description="High-frequency scenario distributions"
    )
    leaderboard: List[TeamMemberAdoptionItem] = Field(
        default_factory=list, description="Ranked adoption leaderboard sorted by productivity"
    )


class AgentActivityEvent(BaseModel):
    """Ingested runtime activity event for ledger aggregation and progression."""

    user_id: str = Field(..., description="Initiating user ID")
    user_name: str = Field(default="Employee", description="User display name")
    agent_id: str = Field(..., description="Invoked agent identifier")
    agent_name: str = Field(..., description="Invoked agent display name")
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    success: bool = Field(default=True)
    task_category: str = Field(default="general", description="Category: code_review, research, data_analysis, etc.")
    timestamp_iso: str = Field(..., description="ISO 8601 timestamp")
