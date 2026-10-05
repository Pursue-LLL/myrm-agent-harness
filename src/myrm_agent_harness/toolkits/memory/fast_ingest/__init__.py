"""Sub-5% Latency One-Pass Fast Ingestion and Async Deep Distillation Engine.

Provides zero-LLM fast memory commit within <5% forward latency overhead
and idle-cycle background deep distillation.
"""

from .distillation import AsyncDeepDistillationWorker
from .models import (
    DistillationBatch,
    DistillationReport,
    FastCommittedRecord,
    IngestionMetrics,
    IngestStatus,
    RawIngestTurn,
)
from .pipeline import FastMemoryCommitPipeline

__all__ = [
    "AsyncDeepDistillationWorker",
    "DistillationBatch",
    "DistillationReport",
    "FastCommittedRecord",
    "FastMemoryCommitPipeline",
    "IngestionMetrics",
    "IngestStatus",
    "RawIngestTurn",
]
