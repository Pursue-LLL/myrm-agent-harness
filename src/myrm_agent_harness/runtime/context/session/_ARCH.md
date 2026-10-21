# runtime/context/session/

## Overview
Session-level context lifecycle domain: volume-backed pinned context files and the checkpoint-thread SSOT of a chat session (thread aliases, deletion).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Aggregate facade re-exporting pins and continuity helpers | ✅ |
| session_context_pins.py | Core | Volume-backed pinned file registry (pinned_context_files.json per session) | ✅ |
| session_continuity.py | Core | Thread aliases of a chat session (`resolve_thread_ids`) and their fail-closed deletion (`clear_checkpoint_threads`, `CheckpointClearError`). A thread that no longer matches the persisted chat history is cleared and the next run rebuilds it from that history. Also the caller-facing contract for who owns the thread: `HISTORY_MODE_CONTEXT_KEY` and `HistoryMode` (`append` default, `continue`, `replace`), resolved per turn in `agent/_internals/turn_history.py`. | ✅ |
| event_sourcing_store.py | Core | Runtime context session event-sourcing persistence layer. | ✅ |

## Module Dependencies

- `langgraph`
- `pydantic`
