"""Session-level context lifecycle domain.

[INPUT]
- Checkpointer thread store protocol (active session detection).
- Session IDs from runtime context cleanup entrypoints.
- LangGraph checkpoint / message store for rewind-truncate-edit-resend SSOT.

[OUTPUT]
- Aggregate facade re-exporting every public name of the ``session`` subpackage:
  - session_activity: active-session ID loading for session-aware cleanup
  - session_context_pins: volume-backed pinned file registry
    (`pinned_context_files.json` per session, cross-compaction retention)
  - session_continuity: checkpoint/message SSOT for rewind/truncate/edit-resend
    (`sync_checkpoint_messages`, `ContinuitySyncError`)

[POS]
Framework generic context-lifecycle capability. Session-scoped activity, pins
and continuity all serve the same runtime lifecycle domain and share the
checkpoint protocol, so they stay co-located under one facade.
"""

from myrm_agent_harness.runtime.context.session.session_activity import (
    load_session_activity,
    load_session_activity_async,
)
from myrm_agent_harness.runtime.context.session.session_context_pins import (
    PinnedContextFiles,
    add_pinned_file,
    read_pinned_files,
    remove_pinned_file,
    write_pinned_files,
)
from myrm_agent_harness.runtime.context.session.session_continuity import (
    ContinuitySyncError,
    resolve_thread_ids,
    sync_checkpoint_messages,
)

__all__ = [
    "ContinuitySyncError",
    "PinnedContextFiles",
    "add_pinned_file",
    "load_session_activity",
    "load_session_activity_async",
    "read_pinned_files",
    "remove_pinned_file",
    "resolve_thread_ids",
    "sync_checkpoint_messages",
    "write_pinned_files",
]
