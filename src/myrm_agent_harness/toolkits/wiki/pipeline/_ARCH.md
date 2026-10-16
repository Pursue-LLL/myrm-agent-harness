# pipeline/

## Overview
Wiki compilation pipeline. SHA256-based incremental compilation, Semaphore-limited parallel
batch ingestion, SQLite persistent queue with auto-retry, purpose-aware article generation
with provenance, HITL pending edits, and bottom-up incremental L0/L1 directory sidecars.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Wiki 编译流水线入口包：聚合导出 WikiCompiler 与 WikiPendingEditsManager | ✅ |
| compiler.py | Core | LLM compiler: parallel batch ingestion, compile structure survey + facet seed carry-forward + **index catalog seed for concept extraction**, compile phase tracking, provenance preservation hook-in (see `compiler_provenance.py`), …; post-batch **vault git snapshot** when `enable_version_control`; `_run_batch` is the one path the background worker and `compile_all` both run (extract, postprocess, settle): a source stays `processing` until everything the compile writes for it is saved, then is marked `completed` (queued again instead when its file changed while the batch ran), or `failed` with the same error classification as an extraction failure if the postprocess raised (see `batch_settle.py`); `enqueue_changed_sources()` hands a host the intake in `compiler_enqueue.py`, so it can give a compile to `start_background_worker` instead of waiting on `compile_all` | ✅ |
| batch_settle.py | Core | Settles a compile batch's queue rows once its results are saved: `settle_extracted` completes the sources whose files are as extraction read them and queues the edited ones again (metadata records the files' hashes as they are at save time and the intake skips `processing` files, so an edit made during a batch would otherwise be lost); `fail_extracted` fails the batch with the extraction classification and a fixed user-facing message; `source_hash` is the hash taken before extraction reads a file | ✅ |
| compiler_enqueue.py | Core | Compile intake: `enqueue_changed_sources` queues the raw files a compile has to read (changed ones when incremental, all when full; a file the worker is compiling right now is left processing) and returns the count; `filter_changed_files` keeps the files whose SHA256 differs from the last compile (hashed on a worker thread, so a large vault does not stall the event loop) | ✅ |
| compiler_provenance.py | Core | Compile-time provenance preservation helpers: `restore_provenance_metadata` re-injects `source_chat`/`source_message`/`compound_provenance` after LLM compile; `provenance_from_raw_sources` seeds them from raw files on first compile | ✅ |
| contradiction_synthesis/ | Core | Cross-concept evolution page synthesis (pairing → LLM verdict → pending) | ✅ |
| postprocess.py | Core | Post-compilation: backlink generation (`generate_backlinks` adds each concept's related concepts to its Related Concepts section through `core/related_links`, so sections after it survive; a page that gains nothing is neither rewritten nor re-indexed; returns links added), metadata persistence with `last_compile_raw_hashes` (merge write: keys other writers keep in `.metadata.json`, such as `raw_supersede` and the link discovery cursor, stay) | ✅ |
| cognitive_map/ | Core | OKF index.md, log.md, hot.md, **SCHEMA.md** deterministic writers + refresh service | ✅ |
| sidecar.py | Core | Directory sidecar builder (`.abstract.md`/`.overview.md`): bottom-up DAG invalidation + incremental rebuild + index sync; LLM summary parsed via `parse_llm_json_object` (robust against fences, prose, bare control chars, trailing commas) | ✅ |
| pending.py | Core | HITL pending edits; `stage_pending_edit` demotes stale published + stores `provenance`; approve blocks stale + uses `publish_concept_article`; **CCSP approve backlinks**; `count_synthesis_pending` SQL; `get_pending_edits`/`get_edits_created_since` paged queries (`limit`+`offset`, newest-first with `id` tiebreaker) — window query status-agnostic (reviewed drafts stay visible) | ✅ |
| publication/ | Core | WPG publish SSOT: `publish_concept_article`, `repair_publication_status`, deterministic fail-closed routing `gate.py` (LLM origins stage, human origins publish) | ✅ |
| apply/ | Core | Narrow-write apply SSOT: `apply_wiki_mutation` (metadata/truth/timeline/create) — agent/chat callers stage as HITL pending drafts | ✅ |
| chat_compound.py | Core | Chat Q&A → pending compound staging (zero LLM · trust claims · source_message dedup) | ✅ |
| raw_gate/ | Core | Raw publication gate SSOT: `publish_raw` (FAIL/SKIP/SUPERSEDE/PUT_IF_ABSENT) + `RAW_SUPERSEDE` audit + `evidence_removal` shared re-anchor | ✅ |
| ingress/ | Core | Browser clip + URL markdown ingress → `publish_raw`; `.wikiignore` patterns — see [ingress/_ARCH.md](ingress/_ARCH.md) | ✅ |
| corpus_dedup/ | Core | Raw corpus dedup governance: fingerprint scan, disposition, compile eligibility filter — see [corpus_dedup/_ARCH.md](corpus_dedup/_ARCH.md) | ✅ |
| queue.py | Core | SQLite persistent ingestion queue with retry + stale recovery + compile circuit pause + eligibility filter on enqueue; a database's first open in a process requeues what a dead process left processing (see `queue_recovery.py`); a batch holds its rows `processing` until all their work is done (`keep_alive` heartbeat, then `complete_processing` / `fail_processing` / `requeue_processing`, which leave a row a newer request put back to pending alone) | ✅ |
| queue_recovery.py | Core | `requeue_orphaned_processing`: on a queue database's first open in this process, returns its `processing` rows to `pending` (a process that died mid-compile owns them, nothing works on them), and the worker the archiver starts compiles them again like any pending row; later opens in the same process leave rows alone because they belong to the live worker; assumes one process per vault | ✅ |
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
- `reset_stale_processing()` recovers items a worker stalled on inside a live process (silent for 300 s, run when the worker loop starts; a live batch refreshes its rows through `queue.keep_alive`, so only silent ones qualify)
- `queue_recovery.requeue_orphaned_processing()` requeues what a dead process left `processing`, once per database per process (the opened-database map is atomic under concurrent opens; a sweep that fails is retried by the next open)
