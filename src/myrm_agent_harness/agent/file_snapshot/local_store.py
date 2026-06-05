"""Local file snapshot store implementation.

Provides workspace file versioning using file-copy snapshots with a JSON manifest.
Snapshots are stored in .myrm/snapshots/{workspace_hash}/{snapshot_id}/.

[POS]
Local filesystem-based file snapshot store.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .types import (
    FileChange,
    FileDiff,
    FileSnapshotInfo,
    RestoreResult,
    SnapshotId,
    SnapshotTrigger,
)

logger = get_agent_logger(__name__)

# Default patterns to exclude from snapshots
DEFAULT_EXCLUDES: set[str] = {
    # Version control
    ".git",
    ".hg",
    ".svn",
    # Dependencies
    "node_modules",
    ".venv",
    "venv",
    "env",
    # Build output
    "dist",
    "build",
    "target",
    "out",
    ".next",
    ".nuxt",
    "__pycache__",
    # Caches
    ".cache",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    # OS files
    ".DS_Store",
    "Thumbs.db",
    # Myrm internal
    ".myrm",
}

# Max file size to snapshot (10 MB)
_MAX_FILE_SIZE = 10 * 1024 * 1024


def _workspace_hash(working_dir: str) -> str:
    """Deterministic per-workspace hash."""
    abs_path = str(Path(working_dir).expanduser().resolve())
    return hashlib.sha256(abs_path.encode()).hexdigest()[:16]


class LocalFileSnapshotStore:
    """Local filesystem-based file snapshot store.

    Snapshots are stored as file copies with a JSON manifest.
    Storage layout:
        .myrm/snapshots/{workspace_hash}/
            {snapshot_id}/
                manifest.json  — file list + metadata
                files/         — copied files preserving directory structure
    """

    def __init__(self, storage_path: Path | None = None) -> None:
        self._storage_path = storage_path or Path(".myrm/snapshots")
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._snapshot_cache: dict[str, set[str]] = {}  # turn_id -> snapshot dirs

    def _workspace_dir(self, working_dir: str) -> Path:
        return self._storage_path / _workspace_hash(working_dir)

    def _snapshot_dir(self, working_dir: str, snapshot_id: SnapshotId) -> Path:
        return self._workspace_dir(working_dir) / snapshot_id

    async def take_snapshot(
        self,
        working_dir: str,
        trigger: SnapshotTrigger,
        description: str = "",
    ) -> SnapshotId:
        """Take a snapshot of the current workspace state."""
        snapshot_id = f"fs_{uuid.uuid4().hex[:12]}_{int(time.time())}"
        snap_dir = self._snapshot_dir(working_dir, snapshot_id)
        files_dir = snap_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        workspace = Path(working_dir).expanduser().resolve()
        if not workspace.exists():
            logger.warning("Workspace does not exist: %s", working_dir)
            return snapshot_id

        manifest: dict[str, object] = {
            "snapshot_id": snapshot_id,
            "working_dir": str(workspace),
            "trigger": trigger.value,
            "created_at": time.time(),
            "description": description,
            "files": {},
        }

        file_count = 0
        try:
            for root, dirs, files in os.walk(workspace):
                # Filter excluded directories in-place
                dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDES]

                for filename in files:
                    src = Path(root) / filename
                    rel_path = src.relative_to(workspace)

                    # Skip large files
                    try:
                        if src.stat().st_size > _MAX_FILE_SIZE:
                            continue
                    except OSError:
                        continue

                    dst = files_dir / rel_path
                    dst.parent.mkdir(parents=True, exist_ok=True)

                    try:
                        shutil.copy2(src, dst)
                        manifest["files"][str(rel_path)] = {  # type: ignore[index]
                            "size": src.stat().st_size,
                            "mtime": src.stat().st_mtime,
                        }
                        file_count += 1
                    except (OSError, PermissionError) as e:
                        logger.debug("Skipping file %s: %s", rel_path, e)

            manifest["file_count"] = file_count

            # Write manifest
            with open(snap_dir / "manifest.json", "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)

            logger.info(
                "Snapshot %s created (trigger=%s, files=%d)",
                snapshot_id,
                trigger.value,
                file_count,
            )

            # Auto-cleanup old snapshots
            await self.cleanup(working_dir)

            return snapshot_id

        except Exception as e:
            # Cleanup partial snapshot
            shutil.rmtree(snap_dir, ignore_errors=True)
            logger.error("Failed to create snapshot: %s", e)
            raise

    async def restore(
        self,
        snapshot_id: SnapshotId,
        files: list[str] | None = None,
    ) -> RestoreResult:
        """Restore workspace to a snapshot state.

        Takes a pre-rollback snapshot before restoring.
        """
        snap_dir = self._find_snapshot_dir(snapshot_id)
        if not snap_dir:
            return RestoreResult(
                success=False,
                snapshot_id=snapshot_id,
                files_restored=0,
                error=f"Snapshot not found: {snapshot_id}",
            )

        manifest_path = snap_dir / "manifest.json"
        if not manifest_path.exists():
            return RestoreResult(
                success=False,
                snapshot_id=snapshot_id,
                files_restored=0,
                error=f"Snapshot manifest missing: {snapshot_id}",
            )

        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        working_dir = manifest["working_dir"]
        files_dir = snap_dir / "files"

        # Take pre-rollback snapshot
        pre_rollback_id = await self.take_snapshot(
            working_dir,
            SnapshotTrigger.PRE_ROLLBACK,
            description=f"Pre-rollback snapshot before restoring {snapshot_id}",
        )

        # Restore files
        restored = 0
        target_files = set(files) if files else None

        try:
            for rel_path_str, _file_meta in manifest.get("files", {}).items():  # type: ignore[assignment]
                if target_files and rel_path_str not in target_files:
                    continue

                src = files_dir / rel_path_str
                dst = Path(working_dir) / rel_path_str

                if not src.exists():
                    continue

                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                restored += 1

            logger.info(
                "Restored %d files from snapshot %s (pre-rollback=%s)",
                restored,
                snapshot_id,
                pre_rollback_id,
            )

            return RestoreResult(
                success=True,
                snapshot_id=snapshot_id,
                files_restored=restored,
                pre_rollback_snapshot_id=pre_rollback_id,
            )

        except Exception as e:
            logger.error("Failed to restore snapshot %s: %s", snapshot_id, e)
            return RestoreResult(
                success=False,
                snapshot_id=snapshot_id,
                files_restored=restored,
                pre_rollback_snapshot_id=pre_rollback_id,
                error=str(e),
            )

    async def diff(self, snapshot_id: SnapshotId) -> FileDiff:
        """Compare a snapshot with current workspace state."""
        snap_dir = self._find_snapshot_dir(snapshot_id)
        if not snap_dir:
            return FileDiff(snapshot_id=snapshot_id)

        manifest_path = snap_dir / "manifest.json"
        if not manifest_path.exists():
            return FileDiff(snapshot_id=snapshot_id)

        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        working_dir = Path(manifest["working_dir"])
        changes: list[FileChange] = []

        snapshot_files: dict[str, dict] = manifest.get("files", {})  # type: ignore[assignment]

        # Check files in snapshot
        for rel_path_str, file_meta in snapshot_files.items():
            current = working_dir / rel_path_str

            if not current.exists():
                changes.append(
                    FileChange(
                        path=rel_path_str,
                        change_type="deleted",
                        old_size=file_meta.get("size"),
                    )
                )
            elif current.stat().st_mtime > file_meta.get("mtime", 0):
                changes.append(
                    FileChange(
                        path=rel_path_str,
                        change_type="modified",
                        old_size=file_meta.get("size"),
                        new_size=current.stat().st_size,
                    )
                )

        # Check for new files not in snapshot
        for root, dirs, files in os.walk(working_dir):
            dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDES]
            for filename in files:
                src = Path(root) / filename
                rel_path = str(src.relative_to(working_dir))
                if rel_path not in snapshot_files:
                    changes.append(
                        FileChange(
                            path=rel_path,
                            change_type="added",
                            new_size=src.stat().st_size,
                        )
                    )

        return FileDiff(
            snapshot_id=snapshot_id,
            changes=changes,
            total_changes=len(changes),
        )

    async def list_snapshots(
        self,
        working_dir: str,
        limit: int = 20,
    ) -> list[FileSnapshotInfo]:
        """List snapshots for a workspace, newest first."""
        ws_dir = self._workspace_dir(working_dir)
        if not ws_dir.exists():
            return []

        snapshots: list[FileSnapshotInfo] = []
        for snap_dir in ws_dir.iterdir():
            if not snap_dir.is_dir():
                continue
            manifest_path = snap_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    manifest = json.load(f)
                snapshots.append(
                    FileSnapshotInfo(
                        snapshot_id=manifest["snapshot_id"],
                        working_dir=manifest["working_dir"],
                        trigger=SnapshotTrigger(manifest["trigger"]),
                        created_at=manifest["created_at"],
                        file_count=manifest.get("file_count", 0),
                        description=manifest.get("description", ""),
                    )
                )
            except Exception as e:
                logger.warning("Failed to read snapshot manifest %s: %s", snap_dir, e)

        snapshots.sort(key=lambda s: s.created_at, reverse=True)
        return snapshots[:limit]

    async def delete_snapshot(self, snapshot_id: SnapshotId) -> bool:
        """Delete a specific snapshot."""
        snap_dir = self._find_snapshot_dir(snapshot_id)
        if not snap_dir:
            return False
        shutil.rmtree(snap_dir, ignore_errors=True)
        logger.info("Deleted snapshot %s", snapshot_id)
        return True

    async def cleanup(
        self,
        working_dir: str,
        max_snapshots: int = 20,
    ) -> int:
        """Cleanup old snapshots, keeping the most recent."""
        snapshots = await self.list_snapshots(working_dir, limit=1000)
        if len(snapshots) <= max_snapshots:
            return 0

        to_delete = snapshots[max_snapshots:]
        deleted = 0
        for snap in to_delete:
            if await self.delete_snapshot(snap.snapshot_id):
                deleted += 1

        if deleted > 0:
            logger.info("Cleaned up %d old snapshots for %s", deleted, working_dir)
        return deleted

    def _find_snapshot_dir(self, snapshot_id: SnapshotId) -> Path | None:
        """Find snapshot directory by ID across all workspaces."""
        for ws_hash_dir in self._storage_path.iterdir():
            if not ws_hash_dir.is_dir():
                continue
            snap_dir = ws_hash_dir / snapshot_id
            if snap_dir.exists():
                return snap_dir
        return None
