# memory_context/

## Overview

User memory injection into model calls — `<user_memory_context>` with scope
boundary and untrusted data wrapping; reuses `memory_brief_snapshot` to avoid
preview/execution drift; records injection/budget telemetry for the server.

Detailed design: [MIDDLEWARE_SYSTEM.md](../MIDDLEWARE_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public export for `MemoryContextMiddleware`. | — |
| `memory_context_middleware.py` | Core | `<user_memory_context>` + scope boundary + untrusted data wrapping; `memory_brief_snapshot` reuse; injection/budget telemetry via API hooks. | ✅ |
| `memory_context_format.py` | Internal | Formatting helpers for memory context injection (XML escaping, budget section partitioning, search guidance, cold-start context). | ✅ |

## Key Dependencies

- `agent.memory` — memory manager
- `langchain_core.messages` — message models
