"""Data models for PersonCard and relationship memory.

[INPUT] Structured/unstructured persona, relations, preferences, and action payloads.
[OUTPUT] PersonCard models, PersonAttributes, and PreActionCheckResult DTOs.
[POS] Harness framework toolkit memory layer for individual persona cards and relationship retention.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RelationType = Literal[
    "self",
    "family",
    "colleague",
    "client",
    "vendor",
    "recruiter",
    "friend",
    "other",
]

DecayStatus = Literal["active", "weak", "archived"]

ActionType = Literal[
    "send_invite",
    "send_email",
    "create_group",
    "assign_task",
    "submit_approval",
    "other",
]


class PersonAttributes(BaseModel):
    """Personal attributes and preferences for a person entity."""

    dietary_restrictions: list[str] = Field(default_factory=list)
    birthday: str | None = None
    timezone: str | None = None
    preferred_contact_hours: str | None = None
    approval_preference: str | None = None
    custom_notes: dict[str, str] = Field(default_factory=dict)


class PersonInteraction(BaseModel):
    """Timestamped record of an interaction with a person."""

    timestamp: str
    summary: str
    channel: str | None = None
    source_event_id: str | None = None


class PersonCard(BaseModel):
    """Bounded person entity card representing a personal relation profile."""

    person_id: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    relation_type: RelationType = "other"
    org: str | None = None
    attributes: PersonAttributes = Field(default_factory=PersonAttributes)
    commitments: list[str] = Field(default_factory=list)
    interaction_timeline: list[PersonInteraction] = Field(default_factory=list)
    last_interaction_at: str | None = None
    confidence: float = 1.0
    scope: Literal["global", "agent"] = "global"
    agent_id: str | None = None
    decay_status: DecayStatus = "active"
    decay_score: float = 1.0


class ParticipantAttributeSummary(BaseModel):
    """Structured inspection summary for a specific participant in an outbound action."""

    person_id: str
    display_name: str
    relation_type: RelationType
    dietary_restrictions: list[str] = Field(default_factory=list)
    timezone: str | None = None
    approval_preference: str | None = None
    missing_critical_attributes: list[str] = Field(default_factory=list)
    is_weak_memory: bool = False
    attributes: PersonAttributes = Field(default_factory=PersonAttributes)


class PreActionCheckResult(BaseModel):
    """Outcome of pre-action attribute verification for proactive fulfillment."""

    action_type: ActionType
    action_summary: str
    has_missing_attributes: bool
    has_weak_memory_warning: bool
    participants: list[ParticipantAttributeSummary] = Field(default_factory=list)
    prompt_cue: str = ""
    warnings: list[str] = Field(default_factory=list)
