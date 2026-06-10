# _manager/

## Overview

Composable `MemoryManager` implementation. External code imports `MemoryManager` from `memory.manager` only.

## Module Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `shared.py` | Barrel | Shared imports, errors, background-task logger | — |
| `core.py` | Mixin | Initialization, properties, backend flags | ✅ |
| `governance_session.py` | Mixin | Approval workflow and session lifecycle | ✅ |
| `retrieval_write.py` | Mixin | Store, search, context, citations | ✅ |
| `convenience.py` | Mixin | Profile and typed add helpers | ✅ |
| `deletion.py` | Mixin | Delete by id, metadata, and type | ✅ |
| `listing_maintenance.py` | Mixin | List, health, archive, backup, maintenance | ✅ |
| `mutations.py` | Mixin | Rate, correct, pin, update | ✅ |
| `storage.py` | Mixin | Backend accessors and private store paths | ✅ |
| `import_export.py` | Mixin | Bulk export (JSON + Markdown), import | ✅ |
| `helpers.py` | Internal | `_memory_ref`, `_infer_preference_category` | — |
| `__init__.py` | Facade | Composes `MemoryManager` | ✅ |
