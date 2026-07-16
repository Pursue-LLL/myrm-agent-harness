"""Memory forgetting strategy based on time decay, access frequency,
importance, and relation count.


[INPUT]
- memory.types::{SemanticMemory, EpisodicMemory, ProceduralMemory} (POS: memory data models)

[OUTPUT]
- ForgettingStrategy: Five-dimension retention scoring (time, frequency, importance, relations, rating)
- ForgettingConfig: Forgetting configuration
- ForgettingMode: Forgetting mode enum (DELETE/ARCHIVE/MARK)
- RetentionReport: Retention score report

[POS]
Forgetting strategy. Calculates retention scores based on time decay, access frequency,
importance, relation count, and user rating. Determines which memories to forget
(delete, archive, or mark). Pinned memories are unconditionally exempt.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, ProceduralMemory, SemanticMemory

logger = logging.getLogger(__name__)

ForgettableMemory = SemanticMemory | EpisodicMemory | ProceduralMemory


class ForgettingMode(StrEnum):
    DELETE = "delete"
    ARCHIVE = "archive"
    MARK = "mark"


@dataclass
class ForgettingConfig:
    time_decay_half_life_days: float = 90.0
    time_weight: float = 0.35
    access_weight: float = 0.25
    max_access_score: int = 20
    importance_weight: float = 0.15
    relation_weight: float = 0.10
    rating_weight: float = 0.15
    min_retention_days: int = 7
    max_relation_score: int = 10
    retention_threshold: float = 0.15
    mode: ForgettingMode = ForgettingMode.ARCHIVE
    max_forget_per_run: int = 100
    protect_high_importance: bool = True
    protect_recent_access: bool = True


@dataclass
class RetentionScore:
    memory_id: str
    total_score: float
    time_score: float
    access_score: float
    importance_score: float
    relation_score: float
    rating_score: float
    should_forget: bool
    reason: str = ""


@dataclass
class ForgettingResult:
    forgotten_count: int = 0
    archived_count: int = 0
    forgotten_ids: list[str] = field(default_factory=list)
    archived_ids: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)


class ForgettingStrategy:
    """Calculates retention scores and selects memories to forget."""

    def __init__(self, config: ForgettingConfig | None = None) -> None:
        self.config = config or ForgettingConfig()

    def calculate_retention_score(self, memory: ForgettableMemory, relation_count: int = 0) -> RetentionScore:
        cfg = self.config
        now = datetime.now(UTC)
        created = memory.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        age_days = (now - created).days

        evd = getattr(memory, "expected_valid_days", None)
        if isinstance(evd, int) and evd > 0:
            time_score = max(0.0, 1.0 - age_days / evd) if age_days < evd else 0.0
        else:
            time_score = 0.5 ** (age_days / cfg.time_decay_half_life_days)
        access_score = min(1.0, memory.access_count / cfg.max_access_score)
        importance_score = memory.importance
        rel_score = min(1.0, relation_count / cfg.max_relation_score)
        rating_score = getattr(memory, "user_rating", 0.5)

        total = (
            time_score * cfg.time_weight
            + access_score * cfg.access_weight
            + importance_score * cfg.importance_weight
            + rel_score * cfg.relation_weight
            + rating_score * cfg.rating_weight
        )

        should_forget = total < cfg.retention_threshold
        reason = ""

        if should_forget:
            if memory.pinned:
                should_forget = False
                reason = "Protected: user-pinned"
            elif age_days < cfg.min_retention_days:
                should_forget = False
                reason = f"Protected: younger than {cfg.min_retention_days} days"
            elif cfg.protect_high_importance and importance_score >= 0.9:
                should_forget = False
                reason = "Protected: high importance"
            elif cfg.protect_recent_access:
                last_accessed = getattr(memory, "last_accessed_at", None)
                if last_accessed:
                    la = last_accessed if last_accessed.tzinfo else last_accessed.replace(tzinfo=UTC)
                    if (now - la).days < 7:
                        should_forget = False
                        reason = "Protected: recently accessed"

        if should_forget and not reason:
            reason = f"Low retention score: {total:.3f}"

        return RetentionScore(
            memory_id=memory.id,
            total_score=total,
            time_score=time_score,
            access_score=access_score,
            importance_score=importance_score,
            relation_score=rel_score,
            rating_score=rating_score,
            should_forget=should_forget,
            reason=reason,
        )

    def select_candidates(
        self, memories: Sequence[ForgettableMemory], relation_counts: dict[str, int] | None = None
    ) -> list[tuple[ForgettableMemory, RetentionScore]]:
        """Score all memories and return those below the retention threshold."""
        rel_counts = relation_counts or {}
        candidates: list[tuple[ForgettableMemory, RetentionScore]] = []
        for mem in memories:
            score = self.calculate_retention_score(mem, rel_counts.get(mem.id, 0))
            if score.should_forget:
                candidates.append((mem, score))
        candidates.sort(key=lambda x: x[1].total_score)
        return candidates[: self.config.max_forget_per_run]
