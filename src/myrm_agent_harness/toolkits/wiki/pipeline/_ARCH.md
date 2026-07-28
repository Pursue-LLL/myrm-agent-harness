# pipeline/

## Overview
Wiki compilation pipeline. SHA256-based incremental compilation, Semaphore-limited parallel
batch ingestion, SQLite persistent queue with auto-retry, purpose-aware article generation
with provenance, HITL pending edits, and bottom-up incremental L0/L1 directory sidecars.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Init | — |
| compiler.py | Core | LLM compiler: parallel batch ingestion, SHA256 incremental cache, purpose injection, frontmatter type compile gate, auto-retry worker | ✅ |
| postprocess.py | Core | Post-compilation: backlink generation, metadata persistence | ✅ |
| cognitive_map/ | Core | OKF index.md, log.md, hot.md deterministic writers + refresh service | ✅ |
| sidecar.py | Core | Directory sidecar builder (`.abstract.md`/`.overview.md`): bottom-up DAG invalidation + incremental rebuild + index sync | ✅ |
| pending.py | Core | HITL pending edits manager; approve blocked on invalid frontmatter `type` | ✅ |
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
