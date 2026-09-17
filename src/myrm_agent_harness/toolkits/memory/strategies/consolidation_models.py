"""Data contracts, models, and callbacks for cross-session memory consolidation.

[INPUT]
- memory.types::ConflictResolution, MemoryType (POS: conflict enum and memory types)

[OUTPUT]
- ConsolidationAction, MergeOp, CorrectOp, UpdateContentOp, ConsolidationOp
- ConsolidationStats, ConsolidationResponse
- ConflictContext, ConflictCallback, ConsolidationCompleteCallback

[POS]
Domain models, DTOs, and protocol callback types for cross-session memory consolidation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.types import (
        ConflictResolution,
        MemoryType,
    )

_PROFILE_KEY_LAST_CONSOLIDATED = "_system.last_consolidated_at"


@dataclass(frozen=True, slots=True)
class ConflictContext:
    """Context passed to the conflict callback when a high-importance correction is uncertain."""

    old_memory_id: str
    old_content: str
    new_content: str
    accuracy_score: float
    importance: float
    merge_suggestion: str
    memory_type: MemoryType


ConflictCallback = Callable[[ConflictContext], Awaitable["ConflictResolution"]]
ConsolidationCompleteCallback = Callable[["ConsolidationStats"], Awaitable[None]]


class ConsolidationAction(StrEnum):
    MERGE = "merge"
    CORRECT = "correct"
    UPDATE_CONTENT = "update_content"


class MergeOp(BaseModel):
    action: str = ConsolidationAction.MERGE
    source_ids: list[str]
    merged_content: str
    importance: float = Field(default=0.7, ge=0.0, le=1.0)
    accuracy_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Score (0-1): Does the merged memory accurately reflect the underlying truth without hallucination?",
    )
    anti_fragmentation_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Score (0-1): Does this operation combine fragmented pieces into a cohesive whole?",
    )
    redundancy_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Score (0-1): Does this operation successfully eliminate duplicate or overlapping information?",
    )
    reasoning: str = Field(default="", description="Reasoning for the scores.")


class CorrectOp(BaseModel):
    action: str = ConsolidationAction.CORRECT
    memory_id: str
    corrected_content: str
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    accuracy_score: float = Field(default=1.0, ge=0.0, le=1.0)
    anti_fragmentation_score: float = Field(default=1.0, ge=0.0, le=1.0)
    redundancy_score: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")


class UpdateContentOp(BaseModel):
    action: str = ConsolidationAction.UPDATE_CONTENT
    memory_id: str
    new_content: str
    importance: float | None = None
    accuracy_score: float = Field(default=1.0, ge=0.0, le=1.0)
    anti_fragmentation_score: float = Field(default=1.0, ge=0.0, le=1.0)
    redundancy_score: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")


ConsolidationOp = MergeOp | CorrectOp | UpdateContentOp


class ConsolidationStats(BaseModel):
    merged: int = 0
    corrected: int = 0
    updated: int = 0
    errors: int = 0
    routed_to_user: int = 0
    guard_patched: int = 0
    total_processed: int = 0
    duration_ms: float = 0.0
    input_count: int = 0
    enriched_count: int = 0
    insights: tuple[str, ...] = ()
    affected_ids: list[str] = Field(default_factory=list)
    aborted: bool = False


class ConsolidationResponse(BaseModel):
    """Parsed LLM consolidation response containing operations and insights."""

    operations: list[ConsolidationOp] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list)


__all__ = [
    "ConflictCallback",
    "ConflictContext",
    "ConsolidationAction",
    "ConsolidationCompleteCallback",
    "ConsolidationOp",
    "ConsolidationResponse",
    "ConsolidationStats",
    "CorrectOp",
    "MergeOp",
    "UpdateContentOp",
    "_PROFILE_KEY_LAST_CONSOLIDATED",
]
