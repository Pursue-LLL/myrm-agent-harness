"""Pure logic for durable background bash job records (BSDL Core).

[INPUT]
- None (stdlib only)

[OUTPUT]
- BackgroundJobRecord: Durable job snapshot for REST / finish dedupe
- reconcile_orphaned_job_ids: Mark running jobs absent from live registry as orphaned
- map_store_status_to_shell_task_status: API status mapping

[POS]
Testable core for BackgroundJobStore — no SQLite or registry coupling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BackgroundJobStoreStatus = Literal["running", "exited", "killed", "orphaned"]
ShellTaskStatus = Literal["running", "completed", "failed", "cancelled", "orphaned"]


@dataclass(frozen=True, slots=True)
class BackgroundJobRecord:
    """Durable metadata for one background bash job."""

    job_id: str
    pid: int | None
    session_id: str
    command: str
    status: BackgroundJobStoreStatus
    started_at: float
    completed_at: float | None
    exit_code: int | None
    error_category: str | None
    finish_processed: bool
    vault_log_ref: str | None


def reconcile_orphaned_job_ids(
    running_job_ids: frozenset[str],
    live_pids: frozenset[int],
    *,
    records_by_job_id: dict[str, BackgroundJobRecord],
) -> tuple[str, ...]:
    """Return job_ids that should flip from running → orphaned after process restart."""
    orphaned: list[str] = []
    for job_id in running_job_ids:
        record = records_by_job_id.get(job_id)
        if record is None:
            continue
        if record.status != "running":
            continue
        pid = record.pid
        if pid is not None and pid in live_pids:
            continue
        orphaned.append(job_id)
    return tuple(orphaned)


def map_store_status_to_shell_task_status(
    status: BackgroundJobStoreStatus,
    exit_code: int | None,
) -> ShellTaskStatus:
    if status == "running":
        return "running"
    if status == "orphaned":
        return "orphaned"
    if status == "killed":
        return "cancelled"
    if status == "exited":
        if exit_code is not None and exit_code != 0:
            return "failed"
        return "completed"
    return "failed"


__all__ = [
    "BackgroundJobRecord",
    "BackgroundJobStoreStatus",
    "ShellTaskStatus",
    "map_store_status_to_shell_task_status",
    "reconcile_orphaned_job_ids",
]
