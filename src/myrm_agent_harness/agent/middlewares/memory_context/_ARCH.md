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
| `memory_context_middleware.py` | Core | `<user_memory_context>` + scope boundary + untrusted data wrapping; `memory_brief_snapshot` reuse; injection/budget telemetry via API hooks (budget carries configured/injected rule counts so trimmed rules are visible to the client). | ✅ |
| `memory_context_format.py` | Internal | Formatting helpers for memory context injection (XML escaping, VETO negative constraint sorting, canonical pattern anchoring, search guidance). | ✅ |
| `memory_context_budget.py` | Internal | Prompt budget partitioning, canonical security token anchoring, and guidance generator helpers (split stable vs untrusted, cold-start prompt builder). | ✅ |

## Key Dependencies

- `agent.memory` — memory manager
- `langchain_core.messages` — message models
