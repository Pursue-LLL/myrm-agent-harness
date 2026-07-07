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
| idle_tasks.py | Core | Default callbacks and tasks for the idle worker. | ✅ |
| shadow_context.py | Core | Execution-layer bulkhead isolation (restricted executor + context manager). | ✅ |
| idle_worker.py | Core | Idle Task Worker for scheduling background tasks when agent is inactive. | ✅ |
| registry.py | Core | Idle Task Registry for crash-resilient persistence and concurrency control. | ✅ |

## Supported Idle Task Types

| Task Type | Description | Handler Location |
|-----------|-------------|-----------------|
| cognitive_consolidation | Merge and consolidate memory fragments | Built-in (idle_tasks.py) |
| cognitive_subsumption | Erase redundant memories when a Skill is learned | Built-in (idle_tasks.py) |
| cognitive_derivation | Deep analysis of implicit user communication preferences | Built-in (idle_tasks.py) |
| session_evidence_extraction | Extract anti-patterns and CAPTURED skill proposals from session events | Built-in (idle_tasks.py) |
| context_compaction | Compress idle session context and preheat prefix cache | Built-in (idle_tasks.py) |

## Key Dependencies

- `runtime`
- `toolkits`
- `agent.context_management`
