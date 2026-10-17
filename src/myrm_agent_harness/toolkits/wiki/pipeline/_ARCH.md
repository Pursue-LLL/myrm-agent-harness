# pipeline/

## Overview
Wiki compilation pipeline. SHA256-based incremental compilation, Semaphore-limited parallel
batch ingestion, SQLite persistent queue with auto-retry, purpose-aware article generation
with provenance, HITL pending edits, and bottom-up incremental L0/L1 directory sidecars.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Wiki 编译流水线入口包：聚合导出 WikiCompiler 与 WikiPendingEditsManager | ✅ |
| compiler.py | Core | LLM compiler: parallel batch ingestion, compile structure survey + facet seed carry-forward + **index catalog seed for concept extraction**, compile phase tracking, provenance preservation hook-in (see `compiler_provenance.py`), …; post-batch **vault git snapshot** when `enable_version_control`; `_run_batch` is the one path the background worker and `compile_all` both run (extract, postprocess, settle): a source stays `processing` until everything the compile writes for it is saved, then is marked `completed` (queued again instead when its file changed while the batch ran), or `failed` with the same error classification as an extraction failure if the postprocess raised, or if an article of one of its concepts could not be written (see `batch_settle.py`); the article stage itself is `articles.py`, reached through the thin `_generate_articles_batch` / `_generate_article` methods; a batch in which no article was written and the failures call for it pauses the circuit through the same rule as a failed extraction batch (`evaluate_batch_pause`); `enqueue_changed_sources()` hands a host the intake in `compiler_enqueue.py`, so it can give a compile to `start_background_worker` instead of waiting on `compile_all` | ✅ |
| batch_settle.py | Core | Settles a compile batch's queue rows once its results are saved: `settle_extracted` queues again the sources whose files changed since extraction read them (metadata records the files' hashes as they are at save time and the intake skips `processing` files, so an edit made during a batch would otherwise be lost), fails the ones behind an article that could not be written (the failure's classification and backoff, the fixed text `Article generation failed`; a transient kind is retried by the worker, a permanent one waits for the user's retry), and completes the rest; `blocked_sources` maps each failed concept to every source it was extracted from and keeps the most severe failure of a source (permanent over transient, then the longer backoff); `fail_extracted` fails the batch with the extraction classification and a fixed user-facing message; `source_hash` is the hash taken before extraction reads a file | ✅ |
| articles.py | Core | The article stage of a compile: `generate_article` writes (or stages for approval) one concept's article from the text of its sources (`article_evidence.py`, read on a worker thread), `generate_articles_batch` runs a batch's concepts with bounded concurrency and returns `ArticleBatchStats`: the counts, the embed pause an index failure asks for, and one `ConceptFailure` per concept whose article could not be written (its sources and `FailureResolution`; an embed window violation is not one, its article is on disk and only the vector index is missing, and the compile pause reports it) | ✅ |
| article_evidence.py | Core | The source text an article is written from: `build_source_evidence` reads each source of a concept (vault-relative `raw/…` refs, sorted, so a retried article sends the same prompt) and returns `### <path>` blocks of `<line number>\| <text>` lines in the template's source slot, using the line numbering of `str.splitlines` that the claims contract slices evidence ranges by; a source within its share of the budget is sent whole, a longer one is cut to its head plus the lines sharing the most terms with the concept's name and definition (`extract_query_terms`) with ±3 neighbours, best matches first, no line longer than a quarter of the budget; the small sources keep what they need and the larger ones split the rest; a source that is missing, unreadable or outside the raw directory is listed by its path only; `source_budget_chars` is `WikiCompileConfig.max_source_context_chars`, lowered to a quarter of the model's context window (a character counted as a token) when that is known and smaller | ✅ |
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

## Failure Policy Decisions

- A source is `completed` only when every article its concepts call for was written. An article that fails marks every source of its concept `failed` (not just the first), so the queue panel shows it and a retry fixes it; a source edited during the batch is queued again instead, since its results are about text that no longer exists.
- The circuit is not paused when a batch raises after extraction. The failed rows are visible in the queue and the next compile trigger starts the worker, which drains the pending rows; a pause would stall every source behind one that fails again until someone resumes it (`compile_all` returns early and the worker sleeps while paused). Pauses are reserved for failures that every further call would repeat: credentials or billing, an embed window violation, a zero-success batch of transient errors (3 or more) or of 5 or more failures of any kind.
