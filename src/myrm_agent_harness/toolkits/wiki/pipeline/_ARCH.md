# pipeline/

## Overview
Wiki compilation pipeline. SHA256-based incremental compilation, Semaphore-limited parallel
batch ingestion, SQLite persistent queue with auto-retry, purpose-aware article generation
with provenance, HITL pending edits.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Init | — |
| compiler.py | Core | LLM compiler: parallel batch ingestion, SHA256 incremental cache, purpose injection, auto-retry worker | ✅ |
| postprocess.py | Core | Post-compilation steps: index building, backlink generation, metadata persistence | ✅ |
| pending.py | Core | HITL pending edits manager | ✅ |
| queue.py | Core | SQLite persistent ingestion queue with retry + stale recovery | ✅ |

## Key Dependencies

- `core` (config, structure, types)
- `retrieval` (indexer for FTS5/edge updates)

## Concurrency Model

- `WikiConfig.parallel_compilation` enables concurrent LLM calls via `asyncio.gather`
- `WikiConfig.max_parallel_workers` controls Semaphore limit (default: 4)
- Concept merging happens serially after all parallel extractions complete (no locks needed)
- Article paths are unique per concept name, preventing file write conflicts
- SQLite operations use transactions for atomicity
- `reset_stale_processing()` recovers items stuck in 'processing' (worker crash resilience)
