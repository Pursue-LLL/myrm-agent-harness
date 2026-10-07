"""ZeroDowntimeCrossDimensionReembeddingEngine package.

Provides blue-green dual collection transitions, dynamic adaptive batching,
and persistent breakpoint recovery for zero-downtime memory re-embedding.

[INPUT]
- toolkits.memory.reembedding.batcher::AdaptiveBatcher (POS: Text-length adaptive batching operator for
  re-embedding pipelines.)
- toolkits.memory.reembedding.checkpoint::CheckpointState, ReembeddingCheckpointManager (POS: Persistent
  checkpoint and breakpoint resume coordinator for re-embedding jobs.)
- toolkits.memory.reembedding.engine::ZeroDowntimeReembeddingEngine (POS: Zero-downtime cross-dimension
  re-embedding orchestrator engine.)
- toolkits.memory.reembedding.models::DualVersionCollectionState, ReembeddingBatch, ReembeddingJobConfig,
  ReembeddingProgress, ReembeddingRecord, ReembeddingStatus (POS: Data models for
  ZeroDowntimeCrossDimensionReembeddingEngine.)

[OUTPUT]
- Package facade re-exporting 10 public names: AdaptiveBatcher, CheckpointState, DualVersionCollectionState,
  ReembeddingBatch, ReembeddingCheckpointManager, ReembeddingJobConfig, ReembeddingProgress,
  ReembeddingRecord, ReembeddingStatus, ZeroDowntimeReembeddingEngine

[POS]
ZeroDowntimeCrossDimensionReembeddingEngine package.
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
