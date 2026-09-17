# checkpointing/

## Overview
Checkpointer factory — creation, configuration, and cleanup for SQLite/Memory backends. SQLite mode fail-fast (no silent MemorySaver fallback).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Checkpointer factory — re-exports create_checkpointer. | — |
| factory.py | Core | Checkpointer factory function. Creates LangGraph-compatible checkpointer instances. | ✅ |
| read_access.py | Core | Checkpoint read access — reads raw thread messages channel with fail-safe degradation. | ✅ |

## Key Dependencies

- `infra` (sqlite_backup)
