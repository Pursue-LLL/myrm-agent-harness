# _internal/

## Overview
Internal implementation details — not part of the public API.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Internal implementation details — not part of the public API. | — |
| approval.py | Core | Approval queue helpers. Handles AnyMemory ↔ PendingRecord conversion for the approval | ✅ |
| embedding_cache.py | Core | Two-tier embedding cache. L1 uses in-memory LRU (OrderedDict + access-count eviction), L2 calls the  | ✅ |
| governance_service.py | Core | Governance-side orchestration. Handles approval flow, profile updates, and content scanning. | ✅ |
| hash_utils.py | Core | Content hash computation utilities for deduplication. | ✅ |
| maintenance.py | Core | Stateless background maintenance operations. Handles dedup, forgetting, access tracking, graph-enriched retrieval (unified scoring for siblings and Claim Graph, parallel traversal, normalized content dedup), Claim Graph compilation, Task Digest evaporation, and Blob GC. | ✅ |
| maintenance_service.py | Core | Maintenance-side orchestration. Handles health assessment, snapshot collection, and triggers Blob GC. | ✅ |
| memory_scanner.py | Core | Memory write-path security scanner. Scans content, raw_exchange, trigger/action fields for prompt injection (7+2 patterns), credential leaks (25+ patterns), and invisible Unicode. Three-tier verdict: BLOCKED/REDACTED/WARN/CLEAN. | ✅ |
| scope.py | Core | Scope helper functions. Handles namespace derivation, MemoryScope binding, write target trimming, namespace validation, and channel affinity. | ✅ |
| search_service.py | Core | Search-side orchestration for memory retrieval. Handles query cleanup, type routing, hybrid candidate collection, ranking, graph enrichment, compact output budgeting, access-count background updates, and business-neutral retrieval trace emission. | ✅ |
| storage.py | Core | Internal storage operations. Handles vector ↔ schema conversion, embedding generation, inline compression, and external BLOB storage. Exports WORKING_STATE constants and TTL parsing in load_context. | ✅ |
| write_service.py | Core | Write-side orchestration for memory persistence. Handles memory scanning, approval routing, | ✅ |

## Key Dependencies

- `core`
