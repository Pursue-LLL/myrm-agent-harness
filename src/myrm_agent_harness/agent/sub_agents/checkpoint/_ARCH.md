# checkpoint/

## Overview
Subagent checkpoint management — lifecycle management (create/save/resume/delete) for subagent execution state with JSON file-based persistence and fcntl file locking. Includes orphan checkpoint scanner that notifies the UI about interrupted tasks on startup.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Subagent checkpoint utilities package. | — |
| checkpoint_manager.py | Core | Subagent checkpoint manager. Handles checkpoint creation, saving, restoration, and deletion. Supports signal handler safe sync extraction. Saves ALL running subagents during shutdown (not just CHECKPOINT strategy). | ✅ |
| metrics.py | Core | Checkpoint metrics data structures. | ✅ |
| orphan_recovery.py | Core | Orphan subagent checkpoint scanner (singleton). Scans checkpoint directory on startup, publishes lifecycle events to notify the UI. Does NOT resume or delete checkpoints. | ✅ |
| saver.py | Core | Subagent checkpoint persistence (JSON file backend). Thread-safe via fcntl.lockf(). Checkpoint includes interruption metadata (reason, recovery_attempts, task_description, accumulated_runtime). | ✅ |
| state_extractor.py | Core | State extraction and restoration. Extracts from _last_context/checkpointer, restores messages via _deserialize_message. | ✅ |

## Key Dependencies

- `utils.logger_utils`
- `agent.sub_agents.types` (SubAgentResult, SubAgentStatus)
- `langchain_core.messages` (message deserialization)
- `langgraph.checkpoint.base` (checkpointer write)
- `runtime.events` (EventBus for recovery lifecycle events)

## Key Design Decisions

- **Signal handler safety**: `save_all_checkpoints()` detects running event loop and falls back to sync extraction via `_create_checkpoint_sync_safe()`
- **Full-scope shutdown save**: `save_all_checkpoints()` saves ALL running subagents regardless of CancellationStrategy, ensuring no state is lost on process restart
- **Per-task timeout**: Each checkpoint save has a 5s timeout guard to prevent shutdown from hanging
- **Thread safety**: `fcntl.lockf()` with LOCK_EX for writes, LOCK_SH for reads
- **Deferred deletion**: `resume_from_checkpoint()` does NOT delete the checkpoint; callers must call `delete_checkpoint()` after successful restoration
- **Message restoration**: `_restore_messages_to_checkpointer()` deserializes messages and writes to LangGraph checkpointer via `aput()`
- **Orphan scanner**: `OrphanRecoveryManager.get_instance().schedule_scan()` scans checkpoints after a 5s startup delay, publishes `orphan_detected` lifecycle events for each interrupted checkpoint. Does NOT attempt to resume or delete — the business layer (resume API + frontend) handles actual recovery
