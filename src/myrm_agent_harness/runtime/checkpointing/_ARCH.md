# checkpointing/

## Overview
Checkpointer factory — creation, configuration, and cleanup for SQLite/Memory backends. SQLite mode fail-fast (no silent MemorySaver fallback). `read_access.py` owns the read-side payload contract: langgraph's `Checkpoint` is a TypedDict, so `aget()` returns a plain `dict` and fields must be read with mapping lookups. `pruning.py` owns the write-side lifecycle: LangGraph keeps every step's checkpoint forever, so the SQLite saver can prune superseded history (`keep_latest`) and hand the space back to the filesystem; the product uses no `DeltaChannel`, which pruning would break (guarded by `tests/architecture/test_no_delta_channel.py`).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Checkpointer factory — re-exports create_checkpointer and read_checkpoint_messages. | — |
| factory.py | Core | Checkpointer factory function. Creates LangGraph-compatible checkpointer instances (SQLite mode builds a `PruningAsyncSqliteSaver` behind the load fallback). Owns the connection on every exit route — including init failures — because an abandoned `aiosqlite` connection pins a non-daemon worker thread that never stops. | ✅ |
| load_fallback.py | Core | `LoadFallbackCheckpointer` — decorator around the SQLite saver. `aget_tuple` reads a checkpoint that cannot be deserialized (corrupt payload, classes removed by an upgrade) as "no checkpoint" so the run starts a fresh session instead of failing every turn. Forwards every async method the wrapped saver implements (`aprune` and `alist_prunable_thread_ids` included); a method left out falls back to the base class and raises `NotImplementedError` (`adelete_thread` is called when a chat's threads are cleared and when a `replace` turn rebuilds its thread). | ✅ |
| pruning.py | Core | `PruningAsyncSqliteSaver` — the SQLite saver plus the `aprune(keep_latest)` upstream leaves unimplemented: deletes checkpoints (and their writes) a newer checkpoint of the same thread and namespace replaced, in byte-bounded transactions that each release the saver lock so concurrent checkpoint writes are never stalled for long, then VACUUMs when enough space is free. `alist_prunable_thread_ids()` names the threads worth pruning; `prune_checkpoint_history(saver)` prunes them all and is a no-op for savers that cannot (memory mode). | ✅ |
| read_access.py | Core | `read_checkpoint_messages()` — single reader of a thread's checkpoint messages channel, shared by the context-budget breakdown (GUI `turn_count`) and subagent checkpoint-state extraction. Degrades to an empty list when the checkpointer, checkpoint, or channel is unavailable. | ✅ |

## Key Dependencies

- `infra` (sqlite_backup)
