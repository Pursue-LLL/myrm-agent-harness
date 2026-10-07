"""Types and models for three tier memory funnel.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ActiveWorkbenchStatus: Layer 1: Real-time active workbench capacity and cognitive gauge status.
- StageNotesAndLedgerStatus: Layer 2: Stage session notes, progress milestones, and negative anti-regression
  ledger.
- SearchableArchiveStatus: Layer 3: Immutable searchable historical conversation archive vault.
- ThreeTierMemoryFunnelSnapshot: Unified Three-Tier Cognitive Memory Funnel snapshot combining Workbench,
  Notes, and Archive.

[POS]
Types and models for three tier memory funnel.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ActiveWorkbenchStatus(BaseModel):
    """Layer 1: Real-time active workbench capacity and cognitive gauge status."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_turns_count: int = Field(default=0, ge=0, description="Number of turns currently loaded in active context")
    current_tokens: int = Field(default=0, ge=0, description="Tokens currently consumed")
    token_limit: int = Field(default=128_000, gt=0, description="Maximum token headroom limit")
    capacity_percentage: float = Field(default=0.0, ge=0.0, le=100.0, description="Token consumption percentage")
    urgency_level: str = Field(
        default="nominal", description="Cognitive gauge urgency (nominal, converging, critical, exhausted)"
    )
    guidance: str = Field(default="EXPLORE_FREELY", description="Action guidance based on headroom")


class StageNotesAndLedgerStatus(BaseModel):
    """Layer 2: Stage session notes, progress milestones, and negative anti-regression ledger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    goal: str = Field(default="", description="Active high-level goal")
    current_step_index: int = Field(default=0, ge=0, description="Current progress step index")
    completed_milestones: list[str] = Field(default_factory=list, description="Milestones concluded")
    active_hypotheses: list[str] = Field(default_factory=list, description="Currently active assumptions")
    key_findings: list[str] = Field(default_factory=list, description="Key validated technical findings")
    disqualified_patterns: list[str] = Field(
        default_factory=list, description="Disqualified/failed approaches to strictly avoid repeating"
    )
    pending_todos: list[str] = Field(default_factory=list, description="Remaining actionable items")


class SearchableArchiveStatus(BaseModel):
    """Layer 3: Immutable searchable historical conversation archive vault."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_archived_turns: int = Field(default=0, ge=0, description="Total turns preserved in immutable archive")
    searchable: bool = Field(default=True, description="Whether full-text / semantic search is currently available")
    last_archived_timestamp: str | None = Field(default=None, description="ISO timestamp of most recent archived turn")


class ThreeTierMemoryFunnelSnapshot(BaseModel):
    """Unified Three-Tier Cognitive Memory Funnel snapshot combining Workbench, Notes, and Archive."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str = Field(..., description="Target session ID")
    active_workbench: ActiveWorkbenchStatus = Field(description="Layer 1 status")
    stage_notes_and_ledger: StageNotesAndLedgerStatus = Field(description="Layer 2 status")
    searchable_archive: SearchableArchiveStatus = Field(description="Layer 3 status")
    snapshot_timestamp_iso: str = Field(..., description="Timestamp when snapshot was compiled")
