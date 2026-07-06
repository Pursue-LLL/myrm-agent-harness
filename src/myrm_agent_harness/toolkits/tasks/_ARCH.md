# tasks/

## Overview
Framework-agnostic async job queue — task models, executor protocol, SQLite persistence.
**Not an agent tool** — no `*_agent_tools.py`; zero LLM token footprint.

Domain-specific media payload DTOs (image async jobs) live in
`toolkits/llms/media_task_types.py`. The worker loop runs in
`myrm-agent-server/app/tasks/worker.py`.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Queue protocol exports (Task, store, executor) | ✅ |
| executor.py | Core | AsyncTaskExecutor protocol for business executors | ✅ |
| protocols.py | Core | Task, TaskStatus, RetryPolicy, state machine | ✅ |
| store.py | Core | SQLiteTaskStore — CRUD, priority, idempotency, cache | ✅ |

## Consumers

| Layer | Location | Usage |
|-------|----------|-------|
| Server worker | `myrm-agent-server/app/tasks/worker.py` | Background task queue processing |
| Server REST | `myrm-agent-server/app/api/tasks/router.py` | Task status API + SSE |
| Harness media | `toolkits/llms/image/async_image_engine.py` | Async image jobs via TaskStore |
| Media DTOs | `toolkits/llms/media_task_types.py` | Typed payloads for media async jobs |

## Key Dependencies

- `core/` — configuration, types
- `utils/` — utility functions

## Forbidden

- `agent/` imports
- Domain-specific payload dataclasses (belong in `llms/media_task_types.py` or server)
