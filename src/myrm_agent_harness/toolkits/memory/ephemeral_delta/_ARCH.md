# ephemeral_delta/

## Overview

Session-scoped tail deltas for cache-safe mid-chat recency; in-memory buffer with SQLite persistence on `memory.db` for process restart recovery.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Prompt-cache-preserving ephemeral session delta memory suite. | ✅ |
| `delta_store.py` | Core | Session buffer + hydrate; append/clear syncs optional persistence. | ✅ |
| `sqlite_persistence.py` | Core | WAL SQLite table on memory.db for restart-safe session deltas. | ✅ |
| `models.py` | Types | Types and models for ephemeral delta. | ✅ |
| `reconciler.py` | Core | Optional batch reconciler for tests/extensions; live chat persistence uses the memory store plus tail notify. | ✅ |
| `tail_injector.py` | Core | Injects active ephemeral session deltas at the tail of the final HumanMessage (XML block with `<precedence>` conflict rule). | ✅ |
| `shared_store.py` | Core | Singleton store; `configure_ephemeral_delta_persistence` (refuses db_path flip while buffers hot) + `ensure_ephemeral_deltas_hydrated`. | ✅ |
| `notify.py` | Core | `record_ephemeral_memory_delta` / `clear_ephemeral_deltas_for_session` after durable writes. | ✅ |
