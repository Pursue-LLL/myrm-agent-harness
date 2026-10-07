"""Sub-5% Latency One-Pass Fast Ingestion and Async Deep Distillation Engine.

Provides zero-LLM fast memory commit within <5% forward latency overhead
and idle-cycle background deep distillation.

[INPUT]
- toolkits.memory.fast_ingest.distillation::AsyncDeepDistillationWorker (POS: Asynchronous Deep Distillation
  Worker executing in idle cycles without user blocking.)
- toolkits.memory.fast_ingest.models::DistillationBatch, DistillationReport, FastCommittedRecord,
  IngestStatus, IngestionMetrics, RawIngestTurn (POS: Data models for Sub-5% Latency One-Pass Fast Ingestion
  and Deep Distillation Engine.)
- toolkits.memory.fast_ingest.pipeline::FastMemoryCommitPipeline (POS: One-Pass Fast Memory Commit Pipeline
  with sub-5% latency overhead guarantee.)

[OUTPUT]
- Package facade re-exporting 8 public names: AsyncDeepDistillationWorker, DistillationBatch,
  DistillationReport, FastCommittedRecord, FastMemoryCommitPipeline, IngestionMetrics, IngestStatus,
  RawIngestTurn

[POS]
Sub-5% Latency One-Pass Fast Ingestion and Async Deep Distillation Engine.
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
