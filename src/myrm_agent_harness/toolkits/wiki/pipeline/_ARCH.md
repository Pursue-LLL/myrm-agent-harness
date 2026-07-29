# pipeline/

## Overview
Wiki compilation pipeline. SHA256-based incremental compilation, Semaphore-limited parallel
batch ingestion, SQLite persistent queue with auto-retry, purpose-aware article generation
with provenance, HITL pending edits, and bottom-up incremental L0/L1 directory sidecars.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Init | — |
| compiler.py | Core | LLM compiler: parallel batch ingestion, purpose injection, frontmatter type gate, **`ensure_compile_claims`**, HITL pending | ✅ |
| postprocess.py | Core | Post-compilation: backlink generation, metadata persistence | ✅ |
| cognitive_map/ | Core | OKF index.md, log.md, hot.md deterministic writers + refresh service | ✅ |
| sidecar.py | Core | Directory sidecar builder (`.abstract.md`/`.overview.md`): bottom-up DAG invalidation + incremental rebuild + index sync | ✅ |
| pending.py | Core | HITL pending edits; `stage_pending_edit` demotes stale published; approve blocks stale + uses `publish_concept_article` | ✅ |
| publication/ | Core | WPG publish SSOT: `publish_concept_article`, `repair_publication_status` | ✅ |
| apply/ | Core | Narrow-write apply SSOT: `apply_wiki_mutation` (metadata/truth/timeline/create) | ✅ |
| raw_gate/ | Core | Raw publication gate SSOT: `publish_raw` (FAIL/SKIP/SUPERSEDE/PUT_IF_ABSENT) + `RAW_SUPERSEDE` audit | ✅ |
| queue.py | Core | SQLite persistent ingestion queue with retry + stale recovery + compile circuit pause | ✅ |
| resilience/ | Core | Compile failure policy (ErrorKind SSOT), circuit pause/resume, display sanitization — see [resilience/_ARCH.md](resilience/_ARCH.md) | ✅ |

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
