"""Session-level context lifecycle domain.

[INPUT]
- LangGraph checkpoint threads of a chat session.

[OUTPUT]
- Aggregate facade re-exporting every public name of the ``session`` subpackage:
  - session_context_pins: volume-backed pinned file registry
    (`pinned_context_files.json` per session, cross-compaction retention)
  - session_continuity: thread aliases of a chat session and their deletion
    (`resolve_thread_ids`, `clear_checkpoint_threads`, `CheckpointClearError`) and the
    `HISTORY_MODE_CONTEXT_KEY` / `HistoryMode` contract a caller uses to declare who owns the thread

[POS]
Framework generic context-lifecycle capability. Session-scoped pins and continuity
serve the same runtime lifecycle domain and share the checkpoint protocol, so they
stay co-located under one facade.
"""

from myrm_agent_harness.runtime.context.session.session_context_pins import (
    PinnedContextFiles,
    add_pinned_file,
    read_pinned_files,
    remove_pinned_file,
    write_pinned_files,
)
from myrm_agent_harness.runtime.context.session.session_continuity import (
    HISTORY_MODE_CONTEXT_KEY,
    CheckpointClearError,
    HistoryMode,
    clear_checkpoint_threads,
    resolve_thread_ids,
)

__all__ = [
    "HISTORY_MODE_CONTEXT_KEY",
    "CheckpointClearError",
    "HistoryMode",
    "PinnedContextFiles",
    "add_pinned_file",
    "clear_checkpoint_threads",
    "read_pinned_files",
    "remove_pinned_file",
    "resolve_thread_ids",
    "write_pinned_files",
]
