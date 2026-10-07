"""[POS]: src/myrm_agent_harness/toolkits/memory/job_compounding/models.py
[INPUT]: Role domain descriptors, approval boundary action lists, and feedback signals.
[OUTPUT]: Immutable Pydantic models for JobDescriptionSpec, CompoundedRule, and CompoundingMaturityReport.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class RuleType(StrEnum):
    """Categorization of compounded domain preference or lesson."""

    POSITIVE_PREFERENCE = "positive_preference"
    NEGATIVE_CONSTRAINT = "negative_constraint"
    INSPECTION_LESSON = "inspection_lesson"


class MaturityTier(StrEnum):
    """Compounding growth tier of the domain agent."""

    ROOKIE = "rookie"
    PRACTITIONER = "practitioner"
    SPECIALIST = "specialist"
    PARTNER = "partner"


class ApprovalBoundarySpec(BaseModel):
    """Specification of what the agent can execute autonomously vs what requires HITL approval."""

    autonomous_actions: list[str] = Field(
        default_factory=list,
        description="Action patterns or tool names the agent can execute independently",
    )
    requires_approval_actions: list[str] = Field(
        default_factory=list,
        description="High-stakes action patterns or tool names requiring explicit human sign-off",
    )


class JobDescriptionSpec(BaseModel):
    """Comprehensive 4-pillar job description specifying role domain, tools, style, and boundaries."""

    agent_id: str = Field(description="Unique agent identifier")
    job_title: str = Field(description="Domain specific title (e.g., Talent Scout, Expense Manager)")
    target_scope: str = Field(description="Pillar 1: Business goal, objective, and operational scope")
    tools_and_sources: list[str] = Field(
        default_factory=list,
        description="Pillar 2: Specific bound tools, datasets, and catalog sources",
    )
    work_style: str = Field(
        default="rigorous",
        description="Pillar 3: Tone and delivery style (e.g. rigorous, conservative, agile)",
    )
    approval_boundary: ApprovalBoundarySpec = Field(
        default_factory=ApprovalBoundarySpec,
        description="Pillar 4: Rigorous action boundaries for autonomy vs human escalation",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp when the job description was established",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of last role calibration or update",
    )


class CompoundedRule(BaseModel):
    """Domain preference, negative constraint, or inspection lesson compounded over time."""

    rule_id: str = Field(description="Unique identifier of the compounded rule")
    agent_id: str = Field(description="Owner agent identifier")
    rule_type: RuleType = Field(description="Preference, constraint, or inspection lesson")
    statement: str = Field(description="Concise, actionable guideline statement")
    trigger_condition: str = Field(description="Condition or scenario where this rule activates")
    evidence_source: str = Field(description="Source conversation or feedback lesson")
    hit_count: int = Field(default=0, ge=0, description="How many times this rule was applied")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of rule establishment",
    )


class CompoundingMaturityReport(BaseModel):
    """Comprehensive evaluation report of the agent's domain compounding maturity."""

    agent_id: str = Field(description="Owner agent identifier")
    job_title: str = Field(description="Configured domain role title")
    total_rules_count: int = Field(ge=0, description="Total active compounded domain rules")
    positive_preferences_count: int = Field(ge=0, description="Count of positive preferences")
    negative_constraints_count: int = Field(ge=0, description="Count of negative constraints")
    inspection_lessons_count: int = Field(ge=0, description="Count of troubleshooting lessons")
    maturity_score: float = Field(ge=0.0, le=100.0, description="Maturity score (0.0 to 100.0)")
    tier: MaturityTier = Field(description="Current maturity stage tier")
    summary: str = Field(description="Human readable progress evaluation summary")
