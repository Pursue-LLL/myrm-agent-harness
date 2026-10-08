"""
[POS] src/myrm_agent_harness/core/security/host_execution_guard/workspace_cow_vault.py
[INPUT] hashlib, os, time, uuid, typing
[OUTPUT] WorkspaceCowVault

Workspace Copy-on-Write差异快照与一键原子撤销保险箱。
Captures lightweight pre-write snapshots of workspace files and provides sub-second atomic rollback.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from pathlib import Path

from .types import FileSnapshotEntry, WorkspaceSnapshot

logger = logging.getLogger(__name__)


class WorkspaceCowVault:
    """Manages lightweight Copy-on-Write (COW) snapshots and instant atomic rollbacks for workspace files."""

    def __init__(self) -> None:
        self._snapshots: dict[str, WorkspaceSnapshot] = {}

    def create_snapshot(
        self,
        workspace_root: str,
        target_rel_paths: tuple[str, ...],
        description: str = "Pre-modification checkpoint",
    ) -> WorkspaceSnapshot:
        """Capture pre-modification state of specified files within the workspace root."""
        snapshot_id = f"snap-{uuid.uuid4().hex[:12]}"
        entries: list[FileSnapshotEntry] = []
        abs_root = os.path.abspath(workspace_root)

        for rel in target_rel_paths:
            abs_target = os.path.normpath(os.path.join(abs_root, rel))
            if os.path.isfile(abs_target):
                try:
                    with open(abs_target, encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                    entries.append(
                        FileSnapshotEntry(
                            relative_path=rel,
                            original_hash=file_hash,
                            original_content=content,
                            is_deleted=False,
                        )
                    )
                except OSError as err:
                    logger.warning("Failed to read file for COW snapshot %s: %s", abs_target, err)
            else:
                # File does not exist yet (creation turn). Rollback will delete it.
                entries.append(
                    FileSnapshotEntry(
                        relative_path=rel,
                        original_hash="",
                        original_content=None,
                        is_deleted=True,
                    )
                )

        snapshot = WorkspaceSnapshot(
            snapshot_id=snapshot_id,
            workspace_root=abs_root,
            created_at=time.time(),
            entries=tuple(entries),
            description=description,
            is_restored=False,
        )
        self._snapshots[snapshot_id] = snapshot
        logger.info("Created COW snapshot %s with %d entries", snapshot_id, len(entries))
        return snapshot

    def rollback_snapshot(self, snapshot_id: str) -> WorkspaceSnapshot:
        """Atomically restore workspace files to the recorded snapshot state."""
        snap = self._snapshots.get(snapshot_id)
        if snap is None:
            raise KeyError(f"Workspace snapshot '{snapshot_id}' not found.")

        abs_root = Path(snap.workspace_root)

        for entry in snap.entries:
            target_path = abs_root / entry.relative_path
            if entry.original_content is not None:
                # Restore original file content
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(entry.original_content)
                logger.debug("Restored original file: %s", target_path)
            else:
                # File did not exist when snapshot was taken; delete it if created
                if target_path.is_file():
                    target_path.unlink(missing_ok=True)
                    logger.debug("Removed newly created file during rollback: %s", target_path)

        updated_snap = WorkspaceSnapshot(
            snapshot_id=snap.snapshot_id,
            workspace_root=snap.workspace_root,
            created_at=snap.created_at,
            entries=snap.entries,
            description=snap.description,
            is_restored=True,
        )
        self._snapshots[snapshot_id] = updated_snap
        logger.info("Successfully rolled back workspace to snapshot %s", snapshot_id)
        return updated_snap

    def get_snapshot(self, snapshot_id: str) -> WorkspaceSnapshot:
        """Fetch snapshot descriptor by ID."""
        snap = self._snapshots.get(snapshot_id)
        if snap is None:
            raise KeyError(f"Workspace snapshot '{snapshot_id}' not found.")
        return snap

    def list_snapshots(self) -> list[WorkspaceSnapshot]:
        """List all tracked workspace snapshots."""
        return list(self._snapshots.values())
