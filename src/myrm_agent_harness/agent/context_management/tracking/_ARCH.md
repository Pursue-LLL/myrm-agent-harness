# tracking/

## Overview
Observation and tracking: artifact tracking, task metrics, cache-TTL pruning savings, archive write/reuse counters and bytes, true prune deferrals, archive budget deferrals, archive refetch cost, archive restore result cost, restore-cost-aware pruning backoff telemetry, structured offload failure kinds, configurable archive restore budgets, restore-map-aware machine-readable archive restore guidance with range hints and content feature summaries, restore allow/block outcome telemetry, net savings after typed restore costs, and recent restore-block events.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Observation and tracking: artifact tracking, task metrics. | — |
| archive_restore.py | Core | Archive restore budget, decision, and restore guidance DTOs backed by the shared runtime restore-map contract for schema validation, path normalization, source-tagged range hints, bounded content feature summaries, and fixed-range fallback reasons. | ✅ |
| archive_restore_runtime.py | Core | Archive restore runtime guard. Applies session ownership and per-task restore budgets before archived content is exposed, and records restore allow/block outcomes for task health aggregation. | ✅ |
| artifact_tracker.py | Core | Artifact trail tracker. Tracks files created, modified, and deleted by the Agent during a session, s | ✅ |
| task_metric_events.py | Core | Serializable compression, adaptive pruning backoff, archive write/reuse, deferral, archive budget deferral, refetch, archive restore outcome, and archive restore block event DTOs with flattened restore hints for GUI/API consumers. | ✅ |
| task_metrics.py | Core | Public task metrics API. Re-exports split metric model, event DTOs, registry helpers, and archive restore guard contracts. | ✅ |
| task_metrics_model.py | Core | TaskMetrics domain model. Owns per-task token/compression/refetch counters, archive write/reuse aggregates, separated deferral aggregates, restore-result cost-adjusted net savings, adaptive pruning backoff aggregates, derived health inputs, and serializable metric summaries. | ✅ |
| task_metrics_restore.py | Core | Archive restore metrics mixin. Owns restore requested/allowed/blocked outcome counters, blocked-ratio calculation, per-path restore budgets, and restore-block detail recording. | ✅ |
| task_metrics_registry.py | Core | Process-local TaskMetrics registry with expiry cleanup and thread-safe lookup. | ✅ |

## Key Dependencies

- `utils`
- `runtime.context`
