"""
[INPUT]: Memory operation telemetry, recall phase traces, backend labels, and latency measurements.
[OUTPUT]: Strongly typed models for memory operation and recall-phase multi-backend metric dimensions.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/memory_backend_metrics/models.py
"""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class MemoryBackendKind(str, Enum):
    """Storage and indexing backend for memory operations."""

    SQLITE_FTS5 = "sqlite_fts5"
    QDRANT = "qdrant"
    IN_MEMORY = "in_memory"
    EXTERNAL = "external"


class MemoryOperationType(str, Enum):
    """Lifecycle memory operation type."""

    RETAIN = "retain"
    RECALL = "recall"
    CONSOLIDATE = "consolidate"


class RecallPhaseType(str, Enum):
    """Granular phase within recall pipeline."""

    COLLECT = "collect"
    FUSE = "fuse"
    RERANK = "rerank"
    NONE = "none"


class MemoryOperationMetricSample(BaseModel):
    """Single metric sample recorded during memory operation."""

    sample_id: str = Field(...)
    backend: MemoryBackendKind = Field(..., description="memories_backend label")
    operation: MemoryOperationType = Field(...)
    phase: RecallPhaseType = Field(default=RecallPhaseType.NONE)
    duration_ms: float = Field(..., ge=0.0)
    success: bool = Field(default=True)
    degraded: bool = Field(default=False, description="True if operation fell back or degraded")
    timestamp_ms: int = Field(...)


class MemoryBackendPerformanceStats(BaseModel):
    """Aggregated latency and throughput metrics for a specific backend."""

    backend: MemoryBackendKind = Field(...)
    operation: MemoryOperationType = Field(...)
    phase: RecallPhaseType = Field(default=RecallPhaseType.NONE)
    total_operations: int = Field(default=0, ge=0)
    success_count: int = Field(default=0, ge=0)
    success_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    degraded_count: int = Field(default=0, ge=0)
    avg_duration_ms: float = Field(default=0.0, ge=0.0)
    p50_duration_ms: float = Field(default=0.0, ge=0.0)
    p95_duration_ms: float = Field(default=0.0, ge=0.0)


class MemoryBackendMetricsReport(BaseModel):
    """Full observability report comparing all active memory backends."""

    opt_in_enabled: bool = Field(default=True, description="Whether memories_backend label dimension is enabled")
    total_samples: int = Field(default=0, ge=0)
    backend_stats: List[MemoryBackendPerformanceStats] = Field(default_factory=list)
    timestamp_ms: int = Field(...)
