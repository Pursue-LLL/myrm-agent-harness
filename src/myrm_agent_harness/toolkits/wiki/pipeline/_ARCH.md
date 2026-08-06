# pipeline/

## Overview
Wiki compilation pipeline. SHA256-based incremental compilation, Semaphore-limited parallel
batch ingestion, SQLite persistent queue with auto-retry, purpose-aware article generation
with provenance, HITL pending edits, and bottom-up incremental L0/L1 directory sidecars.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Init | — |
| compiler.py | Core | LLM compiler: parallel batch ingestion, compile structure survey + facet seed carry-forward + **index catalog seed for concept extraction**, compile phase tracking, …; post-batch **vault git snapshot** when `enable_version_control` | ✅ |
| contradiction_synthesis/ | Core | Cross-concept evolution page synthesis (pairing → LLM verdict → pending) | ✅ |
| postprocess.py | Core | Post-compilation: backlink generation, metadata persistence with `last_compile_raw_hashes` (preserves `raw_supersede`) | ✅ |
| cognitive_map/ | Core | OKF index.md, log.md, hot.md, **SCHEMA.md** deterministic writers + refresh service | ✅ |
| sidecar.py | Core | Directory sidecar builder (`.abstract.md`/`.overview.md`): bottom-up DAG invalidation + incremental rebuild + index sync | ✅ |
| pending.py | Core | HITL pending edits; `stage_pending_edit` demotes stale published + stores `provenance`; approve blocks stale + uses `publish_concept_article`; **CCSP approve backlinks**; `count_synthesis_pending` SQL | ✅ |
| publication/ | Core | WPG publish SSOT: `publish_concept_article`, `repair_publication_status` | ✅ |
| apply/ | Core | Narrow-write apply SSOT: `apply_wiki_mutation` (metadata/truth/timeline/create) | ✅ |
| raw_gate/ | Core | Raw publication gate SSOT: `publish_raw` (FAIL/SKIP/SUPERSEDE/PUT_IF_ABSENT) + `RAW_SUPERSEDE` audit + `evidence_removal` shared re-anchor | ✅ |
| corpus_dedup/ | Core | Raw corpus dedup governance: fingerprint scan, disposition, compile eligibility filter — see [corpus_dedup/_ARCH.md](corpus_dedup/_ARCH.md) | ✅ |
| queue.py | Core | SQLite persistent ingestion queue with retry + stale recovery + compile circuit pause + eligibility filter on enqueue | ✅ |
| survey/ | Core | Zero-LLM compile structure survey (facet seeds, chunk sibling groups, fast-path) — see [survey/_ARCH.md](survey/_ARCH.md) | ✅ |
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
