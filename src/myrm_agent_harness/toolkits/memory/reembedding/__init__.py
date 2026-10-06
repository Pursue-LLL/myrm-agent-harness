"""ZeroDowntimeCrossDimensionReembeddingEngine package.

Provides blue-green dual collection transitions, dynamic adaptive batching,
and persistent breakpoint recovery for zero-downtime memory re-embedding.
"""

from .batcher import AdaptiveBatcher
from .checkpoint import CheckpointState, ReembeddingCheckpointManager
from .engine import ZeroDowntimeReembeddingEngine
from .models import (
    DualVersionCollectionState,
    ReembeddingBatch,
    ReembeddingJobConfig,
    ReembeddingProgress,
    ReembeddingRecord,
    ReembeddingStatus,
)

__all__ = [
    "AdaptiveBatcher",
    "CheckpointState",
    "DualVersionCollectionState",
    "ReembeddingBatch",
    "ReembeddingCheckpointManager",
    "ReembeddingJobConfig",
    "ReembeddingProgress",
    "ReembeddingRecord",
    "ReembeddingStatus",
    "ZeroDowntimeReembeddingEngine",
]
