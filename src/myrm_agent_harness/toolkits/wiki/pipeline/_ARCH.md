# pipeline/

## Overview
Wiki compilation pipeline. SHA256-based incremental compilation, SQLite persistent queue
with auto-retry, purpose-aware article generation with provenance, HITL pending edits.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Init | — |
| compiler.py | Core | LLM compiler: SHA256 incremental cache, purpose injection, auto-retry worker | ✅ |
| pending.py | Core | HITL pending edits manager | ✅ |
| queue.py | Core | SQLite persistent ingestion queue with retry support | ✅ |

## Key Dependencies

- `core` (config, structure, types)
- `retrieval` (indexer for FTS5/edge updates)
