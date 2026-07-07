# tasks/

## Overview

Framework-agnostic async job queue — task models, executor protocol, SQLite persistence.
**Not an agent tool** — no `*_agent_tools.py`; zero LLM token footprint.

Domain-specific media payload DTOs live in `toolkits/llms/media_task_types.py`. The worker
loop, REST/SSE, and payload encryption live in `myrm-agent-server/app/tasks/`.

Detailed design: [TASK_QUEUE_SYSTEM.md](TASK_QUEUE_SYSTEM.md).

## Layer Placement

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend: ImageTaskCard                                    │
├─────────────────────────────────────────────────────────────┤
│  Server: app/api/tasks/ + app/tasks/ + lifecycle/task_worker│
├─────────────────────────────────────────────────────────────┤
│  Harness: toolkits/llms/image/async_image_engine.py         │
├─────────────────────────────────────────────────────────────┤
│  Harness: toolkits/tasks/  ← this module                    │
└─────────────────────────────────────────────────────────────┘
```

## Sibling Modules (job-like systems)

| Module | Use when |
|--------|----------|
| `toolkits/tasks/` | Chat-bound slow media job + `task_id` + progress card |
| `toolkits/cron/` | Scheduled / webhook automation |
| `toolkits/kanban/` | Multi-task board orchestration |
| `web_fetch/task_store.py` | Deep crawl groups only |
| `agent/background_worker/` | Agent idle maintenance (no chat card) |

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Queue protocol exports (Task, store, executor) | ✅ |
| executor.py | Core | AsyncTaskExecutor protocol for business executors | ✅ |
| protocols.py | Core | Task, TaskStatus, RetryPolicy, state machine | ✅ |
| store.py | Core | SQLiteTaskStore — CRUD, priority, idempotency, cache | ✅ |
| TASK_QUEUE_SYSTEM.md | L2 | Placement, scenarios, integration recipes | — |

## Consumers

| Layer | Location | Usage |
|-------|----------|-------|
| Server lifecycle | `myrm-agent-server/app/lifecycle/task_worker.py` | SQLiteTaskStore singleton + worker startup |
| Server worker | `myrm-agent-server/app/tasks/worker.py` | Background task queue processing |
| Server REST | `myrm-agent-server/app/api/tasks/router.py` | Task status API + SSE |
| Harness media | `toolkits/llms/image/async_image_engine.py` | Async image jobs via TaskStore; optional `payload_postprocessor` before persist |
| Media DTOs | `toolkits/llms/media_task_types.py` | Typed payloads for media async jobs |

## Key Dependencies

- `core/` — configuration, types
- `utils/` — utility functions

## Forbidden

- `agent/` imports
- Domain-specific payload dataclasses (belong in `llms/media_task_types.py` or server)
- Worker loop, REST routes, payload encryption (belong in host server)
