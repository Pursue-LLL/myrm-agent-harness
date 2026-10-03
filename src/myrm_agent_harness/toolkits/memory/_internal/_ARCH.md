# _internal/

## Overview
Internal implementation details — not part of the public API.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Internal implementation details — not part of the public API. | — |
| approval.py | Core | Approval queue helpers. Handles AnyMemory ↔ PendingRecord conversion for the approval | ✅ |
| bm25_sparse_index.py | Core | Persistent BM25 sparse mirror. Token hashing (crc32 u31), saturated term-frequency vectors, and the `BM25SparseIndexStore` wrapper that fail-open mirrors every upsert/delete into a `{collection}_bm25` sparse collection and serves BM25 queries from it after a one-shot backfill. `wrap_with_bm25_sparse_index` decides capability by exact `isinstance` at assembly time; legacy backends stay unwrapped on the corpus-scroll fallback path. | ✅ |
| channel_pruning.py | Core | Channel pruning and sub-graph dispatch coordinator with explicit-scope invariance protection. | ✅ |
| embedding_cache.py | Core | Two-tier embedding cache. L1 uses in-memory LRU (OrderedDict + access-count eviction), L2 calls the  | ✅ |
| governance_service.py | Core | Governance-side orchestration. Handles approval flow, profile updates, and content scanning. | ✅ |
| graph_cascade.py | Internal | Cascade graph cleanup for derived nodes upon memory deletion | ✅ |
| hash_utils.py | Core | Content hash computation utilities for deduplication. | ✅ |
| maintenance.py | Core | Stateless background maintenance operations. Handles dedup, forgetting, access tracking, Task Digest evaporation, and Blob GC. Dedup candidates, forgetting, evaporation, and claim compilation are namespace-scoped to never touch other agents' memories. | ✅ |
| maintenance_rule_forgetting.py | Core | Forgetting execution for procedural rules — archives TTL-expired rules (bypassing retention-score threshold) then applies ForgettingStrategy to the rest. | ✅ |
| maintenance_claim_support.py | Internal | Claim graph helper utilities (parsing, scope, relation classification, search). | ✅ |
| maintenance_claim_compile.py | Internal | Claim graph compilation from evaporated L2 digests. | ✅ |
| maintenance_enrichment.py | Internal | Multi-type sub-graph enrichment (Procedural REQUIRES/RESOLVES, Episodic CAUSED_BY, Semantic IS_A/DEFINES + concurrent multi-collection hydration & namespace filtering). | ✅ |
| maintenance_service.py | Core | Maintenance-side orchestration. Runs the periodic cycle (forgetting, staleness review, Task Digest evaporation, claim compilation), health assessment, snapshot collection, and Blob GC. Every archival path (staleness REMOVE included) stamps the retention pair via `types.archive_retention_stamps` so entries stay reclaimable. | ✅ |
| memory_scanner.py | Core | Memory write-path security scanner. Scans content, raw_exchange, trigger/action fields for prompt injection (7+2 patterns), credential leaks (25+ patterns), and invisible Unicode. Three-tier verdict: BLOCKED/REDACTED/WARN/CLEAN. Registers/reads the context-local regex PII pseudonymizer for `MEMORY_WRITE` (closure travels via task context snapshot). | ✅ |
| rerank_gate.py | Core | Cross-encoder rerank gate for the search pipeline. Reorders the fused candidate head after graph enrichment into one relevance order; disabled/timeout/error paths keep the fused order (fail-open). Head scores are replaced by max-normalized cross-encoder scores; the tail keeps fused scores. | ✅ |
| scope.py | Core | Scope helper functions. Handles namespace derivation, MemoryScope binding, durable primary-namespace resolution for new writes (`resolve_primary_namespace`), write target trimming, namespace validation, and channel affinity. | ✅ |
| search_service.py | Core | Search-side orchestration for memory retrieval. Handles query cleanup, dynamic signal weights application for preference-based geometric re-scoring, adaptive channel pruning & sub-graph routing, hybrid candidate collection, ranking, graph enrichment, compact output budgeting, access-count background updates, and business-neutral retrieval trace emission. Retrieval runs under a shared wall-clock deadline (`RetrievalConfig.timeout_seconds`, default 10s): collect uses `asyncio.wait` to keep partial results from fast stores, per-stream tasks track stream kinds and emit machine-stable warning codes (`GATHER_*_TIMEOUT` / `GATHER_*_FAILED`), embed/graph stages fail open on timeout, and degradations are surfaced via `MemoryRetrievalTrace.degraded` + `warning_codes` + degradation metrics. | ✅ |
| storage.py | Core | Internal storage facade. Embedding helpers, store/CRUD operations, and re-exports from submodules. Defines the memory error hierarchy (`MemoryError`, `MemoryNotFoundError`, `MemoryProtectedError`). | ✅ |
| storage_context.py | Core | Context loading for agent prompt (profile, rules, working state). Filters NORMAL-priority tool-failure rules out of the stable layer; user-locked (`is_user_locked`) failure rules graduate into it. Emits user-endorsed (`is_user_locked`) rules first so budget trimming drops them last. | ✅ |
| storage_conversation.py | Core | Conversation memory storage with dual-embedding (Qdrant named vectors). | ✅ |
| storage_converters.py | Core | Document ↔ Schema converters and shared metadata helpers (scope, lifecycle, filter). `_COMMON_KNOWN_KEYS` must only list keys that `doc_to_*` assigns onto the model — listing one without that mapping silently drops it from `metadata` on every round-trip. | ✅ |
| _storage_payload_helpers.py | Core | Payload extraction helpers for document conversion and metadata filtering. | ✅ |
| storage_search.py | Core | Search operations: vector similarity, BM25 keyword (persistent sparse channel first, corpus-scroll fallback with degradation metrics on overflow), profile/procedural text, dual-channel conversation search with RRF fusion. | ✅ |
| temporal_window.py | Core | Temporal window derivation. Parses bilingual past-facing time markers (昨天/上个月/去年春天/last spring/3 weeks ago, Chinese numerals) into wide (since, until) collect-stage hard-filter bounds; explicit bounds always win, fully-future windows fall through to broader markers. | ✅ |
| write_service.py | Core | Write-side orchestration for memory persistence. Handles memory scanning, transient business fact L3 write gate, approval routing, batch dedup, and the write-scope fence (`_validate_write_scope`) that rejects namespaces outside the writer's grant. | ✅ |

## Key Dependencies

- `core`
