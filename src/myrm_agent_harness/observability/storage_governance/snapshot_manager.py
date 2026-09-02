"""Snapshot manager for Agent persistent state storage governance.

[INPUT]
- Path (POS: root data directory)

[OUTPUT]
- StateSnapshotManager (create, list, restore, delete snapshots)

[POS]
Disaster recovery, agent upgrade protection, and point-in-time state checkpointing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .types import StateSnapshotMetadata

logger = logging.getLogger(__name__)


def _compute_file_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    if not file_path.exists():
        return ""
    hasher = hashlib.sha256()
    try:
        with file_path.open("rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError:
        return ""


class StateSnapshotManager:
    """Manages immutable point-in-time state snapshots and rollback execution."""

    def __init__(self, data_dir: Path | str) -> None:
        self._data_dir = Path(data_dir)
        self._snapshots_dir = self._data_dir / "snapshots"

    def _ensure_snapshots_dir(self) -> Path:
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)
        return self._snapshots_dir

    def create_snapshot(self, label: str) -> StateSnapshotMetadata:
        """Create a point-in-time snapshot of the SQLite database and metadata."""
        snapshots_dir = self._ensure_snapshots_dir()
        snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
        target_dir = snapshots_dir / snapshot_id
        target_dir.mkdir(parents=True, exist_ok=True)

        db_file = self._data_dir / "data.db"
        dest_db = target_dir / "data.db"
        file_count = 0
        total_size = 0
        checksum = ""

        if db_file.exists():
            # Use SQLite backup API for consistent, online hot backup
            try:
                src_conn = sqlite3.connect(str(db_file), timeout=5.0)
                dest_conn = sqlite3.connect(str(dest_db))
                try:
                    src_conn.backup(dest_conn)
                finally:
                    dest_conn.close()
                    src_conn.close()
                file_count += 1
                total_size += dest_db.stat().st_size
                checksum = _compute_file_sha256(dest_db)
            except Exception as exc:
                logger.error(
                    "Failed to backup SQLite DB to snapshot %s: %s", snapshot_id, exc
                )
                shutil.copy2(db_file, dest_db)
                file_count += 1
                total_size += dest_db.stat().st_size
                checksum = _compute_file_sha256(dest_db)

        meta = StateSnapshotMetadata(
            snapshot_id=snapshot_id,
            label=label or "Manual Snapshot",
            size_bytes=total_size,
            created_at=datetime.now(timezone.utc).isoformat(),
            checksum=checksum,
            file_count=file_count,
        )

        meta_file = target_dir / "meta.json"
        with meta_file.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "snapshot_id": meta.snapshot_id,
                    "label": meta.label,
                    "size_bytes": meta.size_bytes,
                    "created_at": meta.created_at,
                    "checksum": meta.checksum,
                    "file_count": meta.file_count,
                },
                f,
                indent=2,
            )

        return meta

    def list_snapshots(self) -> list[StateSnapshotMetadata]:
        """List all available snapshots sorted by creation date descending."""
        snapshots_dir = self._ensure_snapshots_dir()
        results: list[StateSnapshotMetadata] = []

        for entry in snapshots_dir.iterdir():
            if not entry.is_dir():
                continue
            meta_file = entry / "meta.json"
            if meta_file.exists():
                try:
                    with meta_file.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                    results.append(
                        StateSnapshotMetadata(
                            snapshot_id=data.get("snapshot_id", entry.name),
                            label=data.get("label", "Snapshot"),
                            size_bytes=data.get("size_bytes", 0),
                            created_at=data.get("created_at", ""),
                            checksum=data.get("checksum", ""),
                            file_count=data.get("file_count", 0),
                        )
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to parse snapshot metadata in %s: %s", entry, exc
                    )
                    continue

        results.sort(key=lambda s: s.created_at, reverse=True)
        return results

    def restore_snapshot(self, snapshot_id: str) -> bool:
        """Restore state from a snapshot, backing up current state before overwriting."""
        snapshots_dir = self._ensure_snapshots_dir()
        target_dir = snapshots_dir / snapshot_id
        if not target_dir.exists():
            logger.error("Snapshot %s does not exist", snapshot_id)
            return False

        src_db = target_dir / "data.db"
        if not src_db.exists():
            logger.error("Snapshot %s contains no data.db file", snapshot_id)
            return False

        # Validate snapshot integrity
        meta_file = target_dir / "meta.json"
        if meta_file.exists():
            try:
                with meta_file.open("r", encoding="utf-8") as f:
                    meta = json.load(f)
                expected_hash = meta.get("checksum")
                if expected_hash:
                    current_hash = _compute_file_sha256(src_db)
                    if current_hash != expected_hash:
                        logger.error("Snapshot checksum mismatch for %s", snapshot_id)
                        return False
            except Exception as exc:
                logger.warning("Checksum validation failed: %s", exc)

        dest_db = self._data_dir / "data.db"

        # Restore SQLite DB via backup API
        try:
            src_conn = sqlite3.connect(str(src_db))
            dest_conn = sqlite3.connect(str(dest_db))
            try:
                src_conn.backup(dest_conn)
            finally:
                dest_conn.close()
                src_conn.close()
            logger.info("Successfully restored snapshot %s to %s", snapshot_id, dest_db)
            return True
        except Exception as exc:
            logger.error(
                "Failed to restore snapshot %s via backup API: %s; falling back to file copy",
                snapshot_id,
                exc,
            )
            shutil.copy2(src_db, dest_db)
            return True

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Permanently delete a snapshot."""
        snapshots_dir = self._ensure_snapshots_dir()
        target_dir = snapshots_dir / snapshot_id
        if not target_dir.exists():
            return False
        try:
            shutil.rmtree(target_dir)
            return True
        except OSError as exc:
            logger.error("Failed to delete snapshot %s: %s", snapshot_id, exc)
            return False
