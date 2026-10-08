# _manager/

## Overview

Composable `MemoryManager` implementation. External code imports `MemoryManager` from `memory.manager` only.

## Module Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `shared.py` | Barrel | Shared imports, errors, background-task logger | — |
| `core.py` | Mixin | Initialization, properties, backend flags, `vector_is_persistent` (exposes underlying vector store persistence — `True` when no vector store or persistent/remote backend, `False` only when embedded degraded to ephemeral `:memory:`), `on_conflict` callback slot | ✅ |
| `governance_session.py` | Mixin | Approval workflow and session lifecycle | ✅ |
| `retrieval_write.py` | Mixin | Store (explicit bypass / inferred force-pending), search (with access tracking and dynamic signal weights passthrough), context | ✅ |
| `convenience.py` | Mixin | Profile and typed add helpers (explicit tool path bypasses pending) | ✅ |
| `deletion.py` | Mixin | Pure deletion: ownership-gated delete by id/metadata/type (vector docs + procedural rules); `allow_protected=False` (agent surface + automated strategies) refuses any `is_user_protected` memory (pinned vector docs or user-locked rules); cascade-cleans derived Claim Graph nodes and evicts embedding cache | ✅ |
| `archival.py` | Mixin | Archival retention: `purge_expired_archived_memories` and `purge_expired_archived_rules` share the `_retention_elapsed` deadline check (authoritative `archive_expires_at`, falling back to `archived_at` + `ARCHIVE_RETENTION_DAYS` for entries archived before the stamp existed), page through the whole archived set (vector cursor / relational offset, page-capped per cycle), and physically reclaim expired entries; memory deletions run after the scan so the cursor stays valid; rules are deleted with `allow_protected=False` so user-endorsed rules stay recoverable | ✅ |
| `queries.py` | Mixin | Metadata queries: list_memory_ids_by_metadata, list_memory_refs_by_metadata, and chat session cascade purge/count | ✅ |
| `listing_maintenance.py` | Mixin | List/count/delete-by-type (EPISODIC bulk clear cascade-cleans Claim Graph nodes), health, archive, backup, maintenance | ✅ |
| `code_compaction.py` | Mixin | Code memory compaction orchestration (compact single snippet or batch of code memories against token budget) | ✅ |
| `experience_evolution.py` | Mixin | Causal experience gene evolution and planning advice (synthesize genes, query dead-end avoidance advice, penalize failures) | ✅ |
| `auto_recall.py` | Mixin | Targeted experience auto-recall gate orchestration (5-scenario trigger filtering, 5-turn sliding dedup, and fail-open rerank) | ✅ |
| `drift_defense.py` | Mixin | Ground truth priority and memory drift stale defense orchestration (sub-5ms physical presence check, symbol verification, stale decoration) | ✅ |
| `sovereign_migration.py` | Mixin | Sovereign asset package migration and cross-machine restore orchestration (atomic .myrmpkg export/restore, path remapping, competitor ingestion) | ✅ |
| `mutations.py` | Mixin | Rate, correct, pin, update; `get_memory` reads within the manager namespaces while an any-namespace existence probe lets approval tell a purged target from one it cannot reach; `update_memory` and `correct_memory` own the single user-protection guard (`allow_protected=False` for automated/agent paths raises `MemoryProtectedError`), and `update_memory` applies `confidence` for semantic memories and treats re-archiving an archived memory as a no-op (retention stamps stay) | ✅ |


| `storage.py` | Mixin | Backend accessors and private store paths | ✅ |
| `import_export.py` | Mixin | Bulk export (JSON + Markdown), import | ✅ |
| `reindex.py` | Mixin | Orphan collection detection and re-embedding after model switch | ✅ |
| `helpers.py` | Internal | `_memory_ref`, `_infer_preference_category` | — |
| `__init__.py` | Facade | Composes `MemoryManager` | ✅ |
| `cross_agent.py` | Mixin | Cross-agent composable context projection (4-layer virtual references), deterministic 3-tier divergence arbitration and sealed task handoffs | ✅ |
| `integration_purge.py` | Mixin | Connector-scoped retained-context auditing, selective purge and provenance revocation | ✅ |
| `kg_screening.py` | Mixin | Knowledge-graph pre-extraction content screening: prompt-injection scan, hidden-HTML stripping, screening audit trail | ✅ |

