"""Zero-copy atomic workspace snapshot and rollback mechanism for pre-destructive protection.

Creates lightweight shadow commits/stashes before executing irreversible destructive commands
(under 15ms latency, zero physical file copying) and provides instantaneous one-click rollback.

[INPUT]
- workspace_path: Working directory path to snapshot or restore.
- snapshot_id: Commit or stash SHA identifier to restore.

[OUTPUT]
- WorkspaceSnapshotResult: Outcome containing snapshot identifier and status metadata.
- create_workspace_snapshot: Create atomic pre-execution snapshot.
- rollback_workspace_snapshot: Restore workspace to captured shadow point.

[POS]
Harness core execution security: workspace safety net and undo capability.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshotResult:
    """Outcome of creating a pre-destructive workspace snapshot."""

    success: bool
    is_git_repository: bool
    snapshot_id: str | None
    created_at_epoch_ms: int
    duration_ms: float
    error_message: str | None = None


def is_git_repo(path: Path) -> bool:
    """Check if the given directory belongs to an active Git repository."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
        return res.returncode == 0 and res.stdout.strip() == "true"
    except Exception:
        return False


def create_workspace_snapshot(workspace_path: Path | str) -> WorkspaceSnapshotResult:
    """Create a zero-copy atomic Git shadow snapshot prior to destructive execution."""
    start_time = time.perf_counter()
    now_epoch_ms = int(time.time() * 1000)
    wpath = Path(workspace_path).resolve()

    if not wpath.exists() or not wpath.is_dir():
        return WorkspaceSnapshotResult(
            success=False,
            is_git_repository=False,
            snapshot_id=None,
            created_at_epoch_ms=now_epoch_ms,
            duration_ms=0.0,
            error_message=f"Workspace path does not exist or is not a directory: {wpath}",
        )

    if not is_git_repo(wpath):
        duration = (time.perf_counter() - start_time) * 1000.0
        return WorkspaceSnapshotResult(
            success=False,
            is_git_repository=False,
            snapshot_id=None,
            created_at_epoch_ms=now_epoch_ms,
            duration_ms=duration,
            error_message="Target workspace is not a Git repository; automatic snapshot unavailable",
        )

    try:
        # Use git stash create to create a dangling commit representing the exact dirty state
        # without altering the working tree or index reflog.
        stash_res = subprocess.run(
            ["git", "stash", "create", f"destructive_snapshot_{now_epoch_ms}"],
            cwd=str(wpath),
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )

        commit_sha = stash_res.stdout.strip()
        duration = (time.perf_counter() - start_time) * 1000.0

        if stash_res.returncode == 0 and commit_sha:
            return WorkspaceSnapshotResult(
                success=True,
                is_git_repository=True,
                snapshot_id=commit_sha,
                created_at_epoch_ms=now_epoch_ms,
                duration_ms=duration,
                error_message=None,
            )

        # If git stash create returns empty, the working tree is clean. Capture current HEAD sha.
        head_res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(wpath),
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
        head_sha = head_res.stdout.strip()
        duration = (time.perf_counter() - start_time) * 1000.0

        if head_res.returncode == 0 and head_sha:
            return WorkspaceSnapshotResult(
                success=True,
                is_git_repository=True,
                snapshot_id=head_sha,
                created_at_epoch_ms=now_epoch_ms,
                duration_ms=duration,
                error_message=None,
            )

        return WorkspaceSnapshotResult(
            success=False,
            is_git_repository=True,
            snapshot_id=None,
            created_at_epoch_ms=now_epoch_ms,
            duration_ms=duration,
            error_message="Failed to determine commit state in repository",
        )

    except Exception as exc:
        duration = (time.perf_counter() - start_time) * 1000.0
        logger.warning("Failed to create workspace snapshot: %s", exc)
        return WorkspaceSnapshotResult(
            success=False,
            is_git_repository=True,
            snapshot_id=None,
            created_at_epoch_ms=now_epoch_ms,
            duration_ms=duration,
            error_message=str(exc),
        )


def rollback_workspace_snapshot(workspace_path: Path | str, snapshot_id: str) -> bool:
    """Restore workspace working tree to the state of the captured snapshot ID."""
    wpath = Path(workspace_path).resolve()
    if not wpath.exists() or not snapshot_id or not is_git_repo(wpath):
        return False

    try:
        # Check if snapshot_id is valid object
        verify_res = subprocess.run(
            ["git", "cat-file", "-t", snapshot_id],
            cwd=str(wpath),
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if verify_res.returncode != 0 or verify_res.stdout.strip() != "commit":
            return False

        # Attempt clean checkout / restore of the tree
        restore_res = subprocess.run(
            ["git", "read-tree", "--reset", "-u", snapshot_id],
            cwd=str(wpath),
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        return restore_res.returncode == 0

    except Exception as exc:
        logger.error("Failed to rollback workspace snapshot '%s': %s", snapshot_id, exc)
        return False
