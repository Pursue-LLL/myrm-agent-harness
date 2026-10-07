"""[POS]: src/myrm_agent_harness/toolkits/memory/proactive_care/models.py
[INPUT]: None.
[OUTPUT]: Strongly-typed schemas for proactive care, fatigue evaluation, and schedule rebalancing.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class FatigueLevelKind(StrEnum):
    """Categorized human fatigue and physical vitality level."""

    NORMAL = "normal"
    MILD_FATIGUE = "mild_fatigue"
    SEVERE_OVERDRAW = "severe_overdraw"


class HealthMetricsRecord(BaseModel):
    """Objective physiological metrics ingested from Apple Health / Android Health."""

    metric_id: str = Field(description="Unique identifier for the health metric event.")
    user_id: str = Field(default="default_user", description="Identifier of the user.")
    timestamp: float = Field(description="Epoch timestamp when the record was taken.")
    sleep_duration_hours: float = Field(
        default=7.5, description="Total sleep hours in the previous cycle."
    )
    deep_sleep_ratio: float = Field(
        default=0.20, description="Ratio of deep sleep compared to total sleep (0.0 - 1.0)."
    )
    daily_steps: int = Field(default=7000, description="Step count recorded on the given day.")
    resting_heart_rate: int = Field(
        default=68, description="Resting heart rate in beats per minute."
    )
    recorded_at_iso: str = Field(
        default="", description="ISO 8601 representation of record timestamp."
    )


class VitalityAssessmentReport(BaseModel):
    """Comprehensive vitality score and multi-modal fatigue causality report."""

    assessment_id: str = Field(description="Unique assessment identifier.")
    user_id: str = Field(default="default_user", description="Identifier of the evaluated user.")
    timestamp: float = Field(description="Epoch timestamp of this assessment.")
    vitality_score: float = Field(
        description="Calculated vitality index ranging from 0.0 (exhausted) to 1.0 (energetic)."
    )
    fatigue_level: FatigueLevelKind = Field(
        description="Categorized fatigue severity based on physical metrics and dialog cues."
    )
    causal_factors: list[str] = Field(
        default_factory=list, description="Extracted causal drivers contributing to fatigue."
    )
    conversational_cues: list[str] = Field(
        default_factory=list,
        description="Linguistic fatigue cues detected from recent conversations.",
    )
    recommendations: list[str] = Field(
        default_factory=list, description="Actionable care suggestions tailored to user state."
    )


class ScheduleTaskItem(BaseModel):
    """An individual schedule or training task subject to elastic adjustment."""

    task_id: str = Field(description="Unique task identifier.")
    title: str = Field(description="Human-readable title of the task.")
    scheduled_date: str = Field(description="Target date formatted as YYYY-MM-DD.")
    intensity_level: int = Field(
        default=3, ge=1, le=5, description="Effort intensity level rated from 1 (light) to 5 (heavy)."
    )
    category: str = Field(
        default="general",
        description="Task category, e.g. workout, coding, deep_work, meeting.",
    )
    is_flexible: bool = Field(
        default=True,
        description="Whether this task can be scaled down or deferred proactively.",
    )
    original_duration_minutes: int = Field(
        default=60, description="Original planned duration in minutes."
    )
    adjusted_duration_minutes: int = Field(
        default=60, description="Dynamically rebalanced duration in minutes."
    )
    status: str = Field(default="active", description="Current status: active, postponed, completed.")


class ScheduleRebalancePlan(BaseModel):
    """Elastic schedule rebalancing plan formulated when fatigue is detected."""

    plan_id: str = Field(description="Unique plan identifier.")
    user_id: str = Field(default="default_user", description="Target user identifier.")
    created_at: float = Field(description="Epoch timestamp of plan generation.")
    fatigue_level: FatigueLevelKind = Field(
        description="Triggering fatigue level prompting this rebalancing."
    )
    load_reduction_ratio: float = Field(
        default=0.0, description="Percentage of load reduction applied (e.g. 0.3 for 30%)."
    )
    tasks_modified: list[ScheduleTaskItem] = Field(
        default_factory=list, description="List of tasks that were elastically adjusted."
    )
    summary: str = Field(description="Architectural rationale and summary of rebalance decisions.")


class CareNotification(BaseModel):
    """High-empathy proactive care message dispatched before user asks."""

    notification_id: str = Field(description="Unique identifier for care notification.")
    user_id: str = Field(default="default_user", description="Target user identifier.")
    timestamp: float = Field(description="Epoch timestamp of notification emission.")
    fatigue_level: FatigueLevelKind = Field(
        description="Severity level associated with the care alert."
    )
    title: str = Field(description="Compassionate notification title.")
    content_message: str = Field(
        description="Warm, thoughtful message explaining adjusted schedule and offering care."
    )
    suggested_actions: list[str] = Field(
        default_factory=list, description="Recommended gentle micro-actions."
    )
    is_read: bool = Field(default=False, description="Whether user has acknowledged this alert.")
