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
| `archival.py` | Mixin | Archival retention: `purge_expired_archived_memories` and `purge_expired_archived_rules` physically reclaim entries past `ARCHIVE_RETENTION_DAYS`, falling back to `archived_at` for entries archived before the expiration stamp existed; rules are deleted with `allow_protected=False` so user-endorsed rules stay recoverable | ✅ |
| `queries.py` | Mixin | Metadata queries: list_memory_ids_by_metadata, list_memory_refs_by_metadata, and chat session cascade purge/count | ✅ |
| `listing_maintenance.py` | Mixin | List/count/delete-by-type (EPISODIC bulk clear cascade-cleans Claim Graph nodes), health, archive, backup, maintenance | ✅ |
| `mutations.py` | Mixin | Rate, correct, pin, update; `update_memory` and `correct_memory` own the single user-protection guard (`allow_protected=False` for automated/agent paths raises `MemoryProtectedError`), and `update_memory` applies `confidence` for semantic memories | ✅ |
| `storage.py` | Mixin | Backend accessors and private store paths | ✅ |
| `import_export.py` | Mixin | Bulk export (JSON + Markdown), import | ✅ |
| `reindex.py` | Mixin | Orphan collection detection and re-embedding after model switch | ✅ |
| `helpers.py` | Internal | `_memory_ref`, `_infer_preference_category` | — |
| `__init__.py` | Facade | Composes `MemoryManager` | ✅ |
