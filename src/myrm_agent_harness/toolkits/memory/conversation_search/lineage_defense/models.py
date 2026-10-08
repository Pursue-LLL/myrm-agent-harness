"""Data models and policies for conversation lineage dedup and automation demotion.

[INPUT]
pydantic::BaseModel (POS: schema definition and validation)
datetime::datetime (POS: temporal ordering and lineage tracking)
typing::Literal, typing::Sequence (POS: typing contracts)

[OUTPUT]
ConversationSourceKind: enum of session origins (interactive, cron, internal_worker).
SourceDemotionPolicy: configuration for automation penalization and filtering.
LineageNode: representation of a session in a compaction/fork tree.
HydrationDetailLevel: level of expanded dialog detail (expanded_window vs compact_card).
HydratedHit: hydrated session search result item.
LineageDedupAuditReport: audit metrics on dedup and demotion efficiency.

[POS]
Harness framework layer models for Item 97 (LineageDedupRecallBlindnessDefenseAndAutomationDemotionSuite).
Strict typing applied: No `any` types allowed. Single file < 400 lines.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ConversationSourceKind(StrEnum):
    """Categorization of session origins for noise filtering and prioritization."""

    INTERACTIVE = "interactive"
    CRON_SCHEDULED = "cron"
    INTERNAL_WORKER = "internal_worker"


class HydrationDetailLevel(StrEnum):
    """Hydration expansion detail level to manage context window footprint."""

    EXPANDED_WINDOW = "expanded_window"
    COMPACT_CARD = "compact_card"


class SourceDemotionPolicy(BaseModel):
    """Governance rules for automation source demotion and filtering."""

    model_config = ConfigDict(extra="forbid")

    cron_weight_multiplier: float = Field(
        default=0.45,
        ge=0.05,
        le=1.0,
        description="Score multiplier for scheduled cron sessions to prevent BM25 domination",
    )
    hide_internal_workers: bool = Field(
        default=True,
        description="Whether to hide background subagent and tool execution workers by default",
    )
    interactive_priority_boost: float = Field(
        default=1.0,
        ge=1.0,
        le=2.0,
        description="Priority boost factor for explicit user interaction sessions",
    )


class LineageNode(BaseModel):
    """A session instance with lineage root and generation tracking."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(description="Unique session identifier")
    lineage_root_id: str = Field(description="Root identifier of the lineage family / compaction root")
    parent_id: str | None = Field(default=None, description="Direct parent session or compaction source")
    generation: int = Field(default=1, ge=1, description="Generation index in the evolution lineage (1=root)")
    source_kind: ConversationSourceKind = Field(
        default=ConversationSourceKind.INTERACTIVE,
        description="Source categorization (interactive, cron, internal_worker)",
    )
    title: str = Field(default="", description="Session title or objective summary")
    raw_score: float = Field(default=0.0, ge=0.0, description="Raw BM25 or similarity retrieval score")
    final_score: float = Field(default=0.0, ge=0.0, description="Score after source-aware demotion")
    messages_context: Sequence[str] = Field(
        default_factory=list,
        description="Sequential message turns in this session for window hydration",
    )
    updated_at: datetime | None = Field(default=None, description="Last modification timestamp")


class HydratedHit(BaseModel):
    """Hydrated search hit item after lineage dedup and window hydration."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    lineage_root_id: str
    title: str
    source_kind: ConversationSourceKind
    detail_level: HydrationDetailLevel
    content_snippet: str
    window_messages: list[str] = Field(default_factory=list)
    token_estimate: int = Field(ge=0, description="Estimated token count for this hit's rendered payload")
    is_demoted: bool = Field(default=False, description="True if score was penalized due to automation source")
    is_lineage_primary: bool = Field(default=True, description="True if selected as representative for lineage root")
    collapsed_generations_count: int = Field(
        default=0,
        ge=0,
        description="Count of older / duplicate generations collapsed under this root",
    )
    collapsed_session_ids: list[str] = Field(
        default_factory=list,
        description="Identifiers of collapsed ancestor/sibling sessions in the same lineage",
    )


class LineageDedupAuditReport(BaseModel):
    """Audit report demonstrating recall blindness defense effectiveness."""

    model_config = ConfigDict(extra="forbid")

    total_candidates: int
    retained_hits_count: int
    hidden_internal_count: int
    demoted_cron_count: int
    collapsed_lineage_count: int
    interactive_top1_ratio: float = Field(
        ge=0.0,
        le=1.0,
        description="Ratio of interactive sessions in top ranks",
    )
    estimated_tokens_saved: int
    token_saving_percent: float = Field(ge=0.0, le=100.0)
