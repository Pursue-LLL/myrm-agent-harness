"""Strongly-typed data models for Life Milestones and Personal Timeline Suite.

[INPUT]
- pydantic::{BaseModel, ConfigDict, Field} (POS: validated immutable data models)

[OUTPUT]
- PrivacyIntimacyLevel: three privacy tiers (open overview, intimate personal, confidential restricted)
- MilestoneCategory, LifeMilestone: lifelong milestone categories and the milestone record (year, narrative, long-term impact, significance, intimacy level)
- ValueSystemNode: belief record with its prior stance, transition catalyst, triggering milestones, active flag and weight
- GrowthDiaryEntry, LifeStageEra: reflective diary entry and the multi-year era segment
- PersonalRetrospectiveCard, ContextProjectionBundle: retrospective card for display and the prompt projection payload

[POS]
Data contracts of the life milestones package, shared by the gate, timeline, projector, aggregator and facade.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PrivacyIntimacyLevel(StrEnum):
    """Privacy and intimacy boundaries for personal milestones and reflections."""

    OPEN_OVERVIEW = "open_overview"  # Public life landmarks (career shifts, public degrees)
    INTIMATE_PERSONAL = "intimate_personal"  # Sensitive life events (family, relationship, values)
    CONFIDENTIAL_RESTRICTED = "confidential_restricted"  # Deeply private (health, trauma, core secrets)


class MilestoneCategory(StrEnum):
    """Macro life milestone categories covering a lifelong journey."""

    CAREER = "career"  # Jobs, startups, career pivots, retirement
    EDUCATION = "education"  # Schools, graduation, certifications, deep learning
    RELOCATION = "relocation"  # Moving cities, immigrating, home purchases
    FAMILY_LIFE = "family_life"  # Marriage, parenthood, family landmarks
    HEALTH_WELLNESS = "health_wellness"  # Health transformations, recovery, lifestyle change
    RELATIONSHIP = "relationship"  # Mentorship, close bonds, lost companions
    VALUE_TRANSFORMATION = "value_transformation"  # Philosophical awakenings, worldview shifts
    PERSONAL_CREATIVE = "personal_creative"  # Writing books, artistic creation, long-term hobbies


class LifeMilestone(BaseModel):
    """A macro life milestone node spanning years or decades."""

    model_config = ConfigDict(frozen=True)

    milestone_id: str = Field(description="Unique milestone identifier")
    timestamp_str: str = Field(description="Event timestamp or ISO date string (e.g. '2021-08-15')")
    year: int = Field(ge=1900, le=2100, description="Calendar year of the event")
    category: MilestoneCategory = Field(description="Milestone domain category")
    title: str = Field(description="Milestone concise title")
    narrative: str = Field(description="Detailed narrative of what transpired")
    long_term_impact: str = Field(description="Description of long-term life trajectory shifts caused by this event")
    core_values: list[str] = Field(default_factory=list, description="Associated values or beliefs linked to this event")
    intimacy_level: PrivacyIntimacyLevel = Field(default=PrivacyIntimacyLevel.OPEN_OVERVIEW, description="Privacy boundary level")
    significance_score: float = Field(default=0.8, ge=0.0, le=1.0, description="Life significance impact weight")
    location: str | None = Field(default=None, description="City or place where milestone occurred")


class ValueSystemNode(BaseModel):
    """Causal lineage node representing evolving personal beliefs and philosophy."""

    model_config = ConfigDict(frozen=True)

    value_id: str = Field(description="Unique value identifier")
    theme: str = Field(description="Belief theme (e.g. 'work_life_balance', 'risk_philosophy')")
    current_stance: str = Field(description="Current guiding stance and belief")
    prior_belief: str | None = Field(default=None, description="Previous stance held before transformation")
    transition_catalyst: str | None = Field(default=None, description="What prompted the value shift")
    trigger_milestone_ids: list[str] = Field(default_factory=list, description="Referenced life milestones causing this shift")
    effective_since_year: int = Field(ge=1900, le=2100, description="Year this stance became dominant")
    is_active: bool = Field(default=True, description="Whether this stance is currently active")
    weight: float = Field(default=1.0, ge=0.1, le=2.0, description="Influence weight on decisions")


class GrowthDiaryEntry(BaseModel):
    """Non-utilitarian reflective growth diary entry capturing personal reflections."""

    model_config = ConfigDict(frozen=True)

    entry_id: str = Field(description="Unique growth diary entry identifier")
    timestamp: datetime = Field(description="Timestamp when reflection was recorded")
    emotional_state: str = Field(description="Emotional state or mind mood (e.g. 'peaceful', 'anxious', 'inspired')")
    reflection_text: str = Field(description="Self-reflective narrative text")
    linked_milestone_id: str | None = Field(default=None, description="Optional link to a major life milestone")
    era_label: str | None = Field(default=None, description="Life era stage label (e.g. 'Fatherhood Era')")


class LifeStageEra(BaseModel):
    """Macro lifecycle era segment grouping years into human stages."""

    model_config = ConfigDict(frozen=True)

    era_id: str = Field(description="Era segment identifier")
    label: str = Field(description="Era title (e.g. 'Early University Explorations', 'First Startup Odyssey')")
    start_year: int = Field(description="Beginning year of era")
    end_year: int | None = Field(default=None, description="Ending year, or None if ongoing")
    guiding_philosophy: str = Field(description="Dominant theme or life philosophy characterizing this era")


class PersonalRetrospectiveCard(BaseModel):
    """Synthesized reflective life retrospective card for UI presentation."""

    model_config = ConfigDict(frozen=True)

    era_label: str = Field(description="Era or timeframe label")
    time_span: str = Field(description="Human readable time span (e.g. '2019 - 2024')")
    milestone_highlights: list[str] = Field(description="Key milestones achieved or experienced")
    dominant_values: list[str] = Field(description="Core value pillars that solidified in this stage")
    growth_reflections: list[str] = Field(description="Poignant reflective insights condensed from diaries")
    companion_empathy_note: str = Field(description="AI empathetic lifelong companion closing perspective")


class ContextProjectionBundle(BaseModel):
    """Context prompt injection payload tailored for deep life choices or reflective dialogues."""

    model_config = ConfigDict(frozen=True)

    projected_text: str = Field(description="Formatted context text to be injected into system/agent prompt")
    relevant_milestone_count: int = Field(ge=0, description="Count of milestones projected")
    active_values: list[str] = Field(description="List of active value principles projected")
    applied_intimacy_level: PrivacyIntimacyLevel = Field(description="Max intimacy level permitted during this projection")
