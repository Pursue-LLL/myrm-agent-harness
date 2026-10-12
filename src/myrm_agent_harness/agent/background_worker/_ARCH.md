# background_worker/

## Overview

Agent idle maintenance — runs when the agent has no active user turn. **Not** `toolkits/tasks/`.

| | `agent/background_worker/` | `toolkits/tasks/` |
|--|------------------------------|-------------------|
| Trigger | Agent idle window | User chat tool call (slow media) |
| Examples | Memory consolidation, context compaction | Async image generation |
| User artifact | None | `task_id` + ImageTaskCard |
| Persistence | `IdleTaskRegistry` | `SQLiteTaskStore` |

See [../../toolkits/tasks/TASK_QUEUE_SYSTEM.md](../../toolkits/tasks/TASK_QUEUE_SYSTEM.md).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Background worker module for agent. | — |
| idle_tasks.py | Core | Default callbacks and tasks for the idle worker. `run_pending_idle_tasks` drains the session queue plus the shared `GLOBAL_SESSION_ID` queue within one idle window (bounded); a window cancelled by a newer turn returns its running task to `pending` via `IdleTaskRegistry.requeue`. | ✅ |
| session_evidence_task.py | Core | Handler of `session_evidence_extraction`: reads this turn's events (bounded by `EventLogger.started_at`) through `EventLogger.backend`/`storage_key` and drafts a CAPTURED skill proposal against the host-registered SkillStore (`register_skill_store_provider`). | ✅ |
| shadow_context.py | Core | Execution-layer bulkhead isolation (restricted executor + context manager). | ✅ |
| idle_worker.py | Core | Idle Task Worker for scheduling background tasks when agent is inactive. | ✅ |
| registry.py | Core | Idle Task Registry for crash-resilient persistence and concurrency control. `running` rows left by a crash are returned to `pending` at init; `acquire_next` serves the session's own queue and `GLOBAL_SESSION_ID`. | ✅ |

## Supported Idle Task Types

| Task Type | Description | Handler Location |
|-----------|-------------|-----------------|
| cognitive_consolidation | Merge and consolidate memory fragments | Built-in (idle_tasks.py) |
| cognitive_subsumption | Erase redundant memories when a Skill is learned | Built-in (idle_tasks.py) |
| session_evidence_extraction | Extract anti-patterns and CAPTURED skill proposals from session events; enqueued only when the run has an `EventLogger` | Built-in (session_evidence_task.py) |
| context_compaction | Compress idle session context via the business-layer handler registered with `register_context_compaction_handler` | Built-in (idle_tasks.py) |

## Key Dependencies

- `runtime`
- `toolkits`
