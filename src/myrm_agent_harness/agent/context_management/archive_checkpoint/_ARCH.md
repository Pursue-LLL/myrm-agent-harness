# archive_checkpoint/

## Overview
Lite-LLM archive summary checkpoints for pruned tool outputs. Persists bounded summaries into EpisodicMemory and exposes hooks for ledger/SSE notification.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `types.py` | Core | `ARCHIVE_CHECKPOINT_EVENT_TYPE`, `ArchiveCheckpointRecord` DTO | ✅ |
| `store.py` | Core | `ArchiveCheckpointStore` Protocol + `EpisodicMemoryArchiveCheckpointStore` + `list_recent_checkpoints` scroll helper | ✅ |
| `summary_service.py` | Core | `ArchiveSummaryService` bounded async dispatch + TaskMetrics telemetry | ✅ |
| `__init__.py` | Package | Public exports | ✅ |

## Key Dependencies

- `toolkits.memory.manager` (EpisodicMemory persistence)
- `infra.schemas.CacheTtlPruneConfig` (queue/concurrency limits)
- `tracking.task_metrics` (archive_summary counters)
