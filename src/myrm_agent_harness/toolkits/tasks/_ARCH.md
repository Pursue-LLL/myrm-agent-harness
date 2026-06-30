# tasks/

## Overview
Framework-agnostic task management — task models, executor protocol, persistence layer.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Tasks toolkit entry point. Aggregates task models, executor protocol, persistence layer. | ✅ |
| executor.py | Core | Task executor protocol — defines the interface for business-layer implementations. | ✅ |
| protocols.py | Core | Task system protocol definitions. | ✅ |
| store.py | Core | Task persistence layer — SQLite-backed CRUD, priority querying, idempotency checks. | ✅ |
| types.py | Config | Task type definitions for common task payloads and results. | ✅ |

## Consumers

| Layer | Location | Usage |
|-------|----------|-------|
| Server worker | `myrm-agent-server/app/tasks/worker.py` | Background task queue processing |
| Server REST | `myrm-agent-server/app/api/tasks/router.py` | Task status API |
| Harness media | `toolkits/llms/image/async_image_engine.py` | Async image generation jobs |

**Not an agent tool** — no `*_agent_tools.py`; zero LLM token footprint.

## Key Dependencies

- `core/` — configuration, types
- `utils/` — utility functions
