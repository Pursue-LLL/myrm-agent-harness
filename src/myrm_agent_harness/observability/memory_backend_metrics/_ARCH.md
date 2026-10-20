# memory_backend_metrics/

## Overview
Opt-in `memories_backend` dimension metrics suite for memory operations (retain/recall/consolidate) and granular recall phases (collect/fuse/rerank).
Inspired by Hindsight PR #5129 to eliminate performance degradation attribution blind spots in multi-backend memory architectures (SQLite FTS5 vs Qdrant vs In-Memory).
Includes dynamic opt-in controls to prevent Prometheus metric cardinality explosion while exposing P50/P95 latencies, success rates, and degradation alerts per backend.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | Public re-exports of models and MemoryBackendMetricsRecorder. | ✅ |
| `models.py` | Domain Models | Pydantic schemas for MemoryBackendKind, MemoryOperationMetricSample, MemoryBackendPerformanceStats, and MemoryBackendMetricsReport. | ✅ |
| `recorder.py` | Core Recorder | MemoryBackendMetricsRecorder managing opt-in gating, sample ingestion, and multi-backend latency percentile aggregations. | ✅ |
