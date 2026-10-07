"""Domain models and type definitions for Ebbinghaus decay and tiered storage lifecycle.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- StorageTier: Tiered storage classification for memory records based on decay strength.
- DecayScorerConfig: Configurable hyperparameters for the Ebbinghaus exponential decay function.
- MemoryDecayProfile: Lifecycle and decay tracking state attached to an individual memory item.
- DecayRerankItem: Scored memory retrieval candidate with blended similarity and decay weights.
- TierMigrationReport: Audit report generated following periodic evaluation and tiered migration.

[POS]
Domain models and type definitions for Ebbinghaus decay and tiered storage lifecycle.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class StorageTier(StrEnum):
    """Tiered storage classification for memory records based on decay strength."""

    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"


@dataclass(frozen=True)
class DecayScorerConfig:
    """Configurable hyperparameters for the Ebbinghaus exponential decay function."""

    lambda_decay: float = 0.05
    alpha_freq: float = 0.3
    hot_threshold: float = 0.6
    cold_threshold: float = 0.2
    cold_min_age_days: float = 30.0


@dataclass
class MemoryDecayProfile:
    """Lifecycle and decay tracking state attached to an individual memory item."""

    memory_id: str
    content: str
    importance: float
    created_at: float
    last_accessed_at: float
    access_count: int
    pinned: bool = False
    current_score: float = 1.0
    current_tier: StorageTier = StorageTier.HOT


@dataclass(frozen=True)
class DecayRerankItem:
    """Scored memory retrieval candidate with blended similarity and decay weights."""

    memory_id: str
    content: str
    base_similarity: float
    decay_score: float
    final_score: float
    tier: StorageTier


@dataclass(frozen=True)
class TierMigrationReport:
    """Audit report generated following periodic evaluation and tiered migration."""

    total_evaluated: int
    hot_count: int
    warm_count: int
    cold_count: int
    migrated_count: int
    migrated_memory_ids: list[str] = field(default_factory=list)
