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
| `deletion.py` | Mixin | Pure deletion: ownership-gated delete by id/metadata/type (vector docs + procedural rules); `allow_protected=False` (agent surface + automated strategies) refuses any `is_user_protected` memory (pinned vector docs or user-locked rules); cascade-cleans derived Claim Graph nodes and evicts embedding cache; metadata cascade and `delete_all` reach every embedding model's collections (`model_collections`), `delete_all` includes conversations and raises once every backend was tried when a relational or vector deletion failed | ✅ |
| `archival.py` | Mixin | Archival retention: `purge_expired_archived_memories` and `purge_expired_archived_rules` share the `_retention_elapsed` deadline check (authoritative `archive_expires_at`, falling back to `archived_at` + `ARCHIVE_RETENTION_DAYS` for entries archived before the stamp existed), page through the whole archived set (vector cursor / relational offset, page-capped per cycle), and physically reclaim expired entries; memory deletions run after the scan so the cursor stays valid; rules are deleted with `allow_protected=False` so user-endorsed rules stay recoverable | ✅ |
| `queries.py` | Mixin | Metadata queries: list_memory_ids_by_metadata, list_memory_refs_by_metadata, and chat session cascade purge/count; the id listing (and so the deletion preview) spans every embedding model's collections | ✅ |
| `listing_maintenance.py` | Mixin | List/count/delete-by-type (EPISODIC bulk clear cascade-cleans Claim Graph nodes), health, archive, backup, maintenance; delete-by-type also clears the previous embedding models' collections | ✅ |
| `sovereign_migration.py` | Mixin | Sovereign asset package migration and cross-machine restore orchestration (atomic .myrmpkg export/restore, path remapping, competitor ingestion) | ✅ |
| `mutations.py` | Mixin | Rate, correct, pin, update; `get_memory` reads within the manager namespaces while an any-namespace existence probe lets approval tell a purged target from one it cannot reach; `update_memory` and `correct_memory` own the single user-protection guard (`allow_protected=False` for automated/agent paths raises `MemoryProtectedError`), and `update_memory` applies `confidence` for semantic memories and treats re-archiving an archived memory as a no-op (retention stamps stay) | ✅ |


| `storage.py` | Mixin | Backend accessors and private store paths | ✅ |
| `import_export.py` | Mixin | Bulk export (JSON + Markdown), import | ✅ |
| `model_collections.py` | Internal | Single reader of the per-model collection naming (`{prefix}_{type}_{model}`): current vs previous models' collections (sparse `_bm25` mirrors excluded), `memory_collections` per type for reindex and bulk deletion, `retire_if_drained` | — |
| `reindex.py` | Mixin | Embedding-model switch migration: orphan detection (previous models' collections, sized with `count` so named-vector conversation collections are seen) and per-memory move into the current model's collections — payload copied verbatim, vector re-embedded, ids already present not embedded again; a memory leaves the old collection only after the current one is read back to hold it, an emptied old collection is dropped with its BM25 mirror, every read/embed/write/removal failure is counted as `failed` and stays for the next run | ✅ |
| `helpers.py` | Internal | `_memory_ref`, `_infer_preference_category` | — |
| `__init__.py` | Facade | Composes `MemoryManager` | ✅ |

