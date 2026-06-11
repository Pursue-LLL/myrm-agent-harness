"""In-process inbox for file-restore notifications to the Agent.

When the user performs a file rollback via the GUI, the server writes a
notification here. On the next Agent turn, ``agent_runtime`` drains this
inbox and injects a ``HumanMessage`` so the Agent becomes aware of the
workspace state change — preventing hallucinations from stale context.

Thread-safe: uses a simple deque with no external dependencies.

[POS]
File restore notification inbox — bridges server restore API and Agent context.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

_NOTIFICATION_TTL_SECONDS = 600.0


@dataclass(frozen=True, slots=True)
class RestoreNotification:
    """Pending notification about a file restore event."""

    snapshot_id: str
    files_restored: int
    restored_files: list[str] | None
    timestamp: float


_pending: deque[RestoreNotification] = deque()


def push_restore_notification(
    snapshot_id: str,
    files_restored: int,
    restored_files: list[str] | None = None,
) -> None:
    """Called by the server restore API after a successful rollback."""
    _pending.append(
        RestoreNotification(
            snapshot_id=snapshot_id,
            files_restored=files_restored,
            restored_files=restored_files,
            timestamp=time.time(),
        )
    )


def drain_restore_notifications() -> str | None:
    """Drain all pending restore notifications into a single formatted string.

    Discards notifications older than TTL. Returns None if empty.
    """
    if not _pending:
        return None

    now = time.time()
    parts: list[str] = []
    while _pending:
        notif = _pending.popleft()
        if (now - notif.timestamp) > _NOTIFICATION_TTL_SECONDS:
            continue
        msg = f"[System: File rollback detected] "
        if notif.restored_files:
            file_list = ", ".join(notif.restored_files[:10])
            msg += f"{notif.files_restored} file(s) restored to snapshot {notif.snapshot_id[:8]}. Affected: {file_list}"
            if len(notif.restored_files) > 10:
                msg += f" (+{len(notif.restored_files) - 10} more)"
        else:
            msg += f"Entire workspace ({notif.files_restored} files) restored to snapshot {notif.snapshot_id[:8]}."
        msg += (
            " The workspace files have changed externally. "
            "Re-read any files you previously modified before making further changes."
        )
        parts.append(msg)

    return "\n".join(parts) if parts else None
