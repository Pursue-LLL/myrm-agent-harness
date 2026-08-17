# _manager/

## Overview

Composable `MemoryManager` implementation. External code imports `MemoryManager` from `memory.manager` only.

## Module Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `shared.py` | Barrel | Shared imports, errors, background-task logger | — |
| `core.py` | Mixin | Initialization, properties, backend flags, `vector_is_persistent` (exposes underlying vector store persistence — `True` when no vector store or persistent/remote backend, `False` only when embedded degraded to ephemeral `:memory:`), `on_conflict` callback slot | ✅ |
| `governance_session.py` | Mixin | Approval workflow and session lifecycle | ✅ |
| `retrieval_write.py` | Mixin | Store, search (with access tracking), context | ✅ |
| `convenience.py` | Mixin | Profile and typed add helpers | ✅ |
| `deletion.py` | Mixin | Ownership-gated delete by id/metadata/type (vector docs + procedural rules); ownership keys on `primary_namespace` (exact) with a namespaces-intersection fallback for legacy docs; cascade-cleans derived Claim Graph nodes | ✅ |
| `listing_maintenance.py` | Mixin | List/count/delete-by-type (EPISODIC bulk clear cascade-cleans Claim Graph nodes), health, archive, backup, maintenance | ✅ |
| `mutations.py` | Mixin | Rate, correct, pin, update | ✅ |
| `storage.py` | Mixin | Backend accessors and private store paths | ✅ |
| `import_export.py` | Mixin | Bulk export (JSON + Markdown), import | ✅ |
| `reindex.py` | Mixin | Orphan collection detection and re-embedding after model switch | ✅ |
| `helpers.py` | Internal | `_memory_ref`, `_infer_preference_category` | — |
| `__init__.py` | Facade | Composes `MemoryManager` | ✅ |
