# checkpoint/

## Overview
Subagent checkpoint management — lifecycle management (create/save/resume/delete) for subagent execution state with JSON file-based persistence using crash-consistent atomic writes. Includes orphan checkpoint scanner that notifies the UI about interrupted tasks on startup.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Subagent checkpoint utilities package. | — |
| checkpoint_manager.py | Core | Subagent checkpoint manager. Handles checkpoint creation, saving, restoration, and deletion. Supports signal handler safe sync extraction. Saves ALL running subagents during shutdown (not just CHECKPOINT strategy). | ✅ |
| metrics.py | Core | Checkpoint metrics data structures. | ✅ |
| orphan_recovery.py | Core | Orphan subagent checkpoint scanner (singleton). Scans checkpoint directory on startup, publishes lifecycle events to notify the UI. Does NOT resume or delete checkpoints. | ✅ |
| saver.py | Core | Subagent checkpoint persistence (JSON file backend). Default path: `MYRM_DATA_DIR/checkpoints` or `.myrm/checkpoints`. Validates `task_id` as safe filename. Crash-consistent via `infra.atomic_write` (temp file + fsync + atomic rename); raises `CheckpointCorruptedError` for unparseable files. | ✅ |
| state_extractor.py | Core | State extraction and restoration. Extracts from _last_context/checkpointer, restores messages via _deserialize_message. | ✅ |

## Key Dependencies

- `utils.logger_utils`
- `agent.sub_agents.types` (SubAgentResult, SubAgentStatus)
- `langchain_core.messages` (message deserialization)
- `langgraph.checkpoint.base` (checkpointer write)
- `runtime.events` (EventBus for recovery lifecycle events)
- `infra.atomic_write` (crash-consistent file writes)

## Key Design Decisions

- **Signal handler safety**: `save_all_checkpoints()` detects running event loop and falls back to sync extraction via `_create_checkpoint_sync_safe()`
- **Full-scope shutdown save**: `save_all_checkpoints()` saves ALL running subagents regardless of CancellationStrategy, ensuring no state is lost on process restart
- **Per-task timeout**: Each checkpoint save has a 5s timeout guard to prevent shutdown from hanging
- **Crash consistency**: `save_sync()` writes through `infra.atomic_write.atomic_write()` (temp file + fsync + atomic rename), so a crash mid-write never leaves a partial JSON file. No `fcntl` locks needed — readers always observe a complete file.
- **Corrupted-file handling**: `load()` raises `CheckpointCorruptedError` (not a generic error) for unparseable files so the business layer can return a client-friendly error. `cleanup_old_checkpoints()` deletes unparseable files instead of skipping them, so the TTL never leaks corrupted files.
- **Deferred deletion**: `resume_from_checkpoint()` does NOT delete the checkpoint; callers must call `delete_checkpoint()` after successful restoration
- **Message restoration**: `_restore_messages_to_checkpointer()` deserializes messages and writes to LangGraph checkpointer via `aput()`
- **Orphan scanner**: `OrphanRecoveryManager.get_instance().schedule_scan()` scans checkpoints after a 5s startup delay, publishes `orphan_detected` lifecycle events for each interrupted checkpoint. Does NOT attempt to resume or delete — the business layer (resume API + frontend) handles actual recovery
