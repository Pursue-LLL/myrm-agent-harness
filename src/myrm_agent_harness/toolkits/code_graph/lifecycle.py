"""Graph data lifecycle management — workspace-hashed DB naming, TTL cleanup.

Manages the lifecycle of code graph databases: creation, workspace isolation
via content-addressed naming, and TTL-based cleanup of stale databases.

[INPUT]
- Path (POS: MYRM_DATA_DIR base directory)

[OUTPUT]
- CodeGraphLifecycle: lifecycle management for graph databases
- WorkspaceInfo: metadata about a workspace's graph database

[POS]
Data lifecycle layer ensuring each workspace gets isolated graph storage with
automatic cleanup of abandoned databases. Prevents unbounded disk usage.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from myrm_agent_harness.toolkits.code_graph.parser import register_custom_parsers
from myrm_agent_harness.toolkits.code_graph.store import CodeGraphStore

logger = logging.getLogger(__name__)

DEFAULT_TTL_DAYS = 30
CODE_GRAPH_SUBDIR = "code_graph"


@dataclass(frozen=True, slots=True)
class WorkspaceInfo:
    """Metadata about a workspace's graph database."""

    workspace_root: str
    workspace_hash: str
    db_path: Path
    exists: bool
    size_bytes: int = 0
    last_modified: float = 0.0


class CodeGraphLifecycle:
    """Manages code graph database lifecycle."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._graph_dir = data_dir / CODE_GRAPH_SUBDIR

    def ensure_directory(self) -> Path:
        """Create the code_graph directory if it doesn't exist."""
        self._graph_dir.mkdir(parents=True, exist_ok=True)
        return self._graph_dir

    def get_workspace_info(self, workspace_root: str) -> WorkspaceInfo:
        """Get info about a workspace's graph database."""
        ws_hash = _workspace_hash(workspace_root)
        db_path = self._graph_dir / f"{ws_hash}.db"

        size_bytes = 0
        last_modified = 0.0
        exists = db_path.exists()
        if exists:
            try:
                stat = db_path.stat()
                size_bytes = stat.st_size
                last_modified = stat.st_mtime
            except OSError:
                pass

        return WorkspaceInfo(
            workspace_root=workspace_root,
            workspace_hash=ws_hash,
            db_path=db_path,
            exists=exists,
            size_bytes=size_bytes,
            last_modified=last_modified,
        )

    def open_store(self, workspace_root: str) -> CodeGraphStore:
        """Open (or create) a CodeGraphStore for the given workspace.

        Also loads custom language parsers from languages.toml in the workspace root
        if the file exists, extending the supported language set dynamically.
        """
        self.ensure_directory()
        db_path = CodeGraphStore.workspace_db_path(self._data_dir, workspace_root)
        store = CodeGraphStore(db_path)
        store.open()

        languages_toml = Path(workspace_root) / "languages.toml"
        if languages_toml.exists():
            register_custom_parsers(languages_toml)

        return store

    def list_workspaces(self) -> list[WorkspaceInfo]:
        """List all workspace graph databases."""
        if not self._graph_dir.exists():
            return []

        workspaces: list[WorkspaceInfo] = []
        for db_file in self._graph_dir.glob("*.db"):
            ws_hash = db_file.stem
            try:
                stat = db_file.stat()
                workspaces.append(WorkspaceInfo(
                    workspace_root="",
                    workspace_hash=ws_hash,
                    db_path=db_file,
                    exists=True,
                    size_bytes=stat.st_size,
                    last_modified=stat.st_mtime,
                ))
            except OSError:
                continue

        return workspaces

    def cleanup_stale(self, *, ttl_days: int = DEFAULT_TTL_DAYS) -> int:
        """Remove graph databases not accessed within TTL period."""
        if not self._graph_dir.exists():
            return 0

        cutoff = time.time() - (ttl_days * 86400)
        removed = 0

        for db_file in self._graph_dir.glob("*.db"):
            try:
                stat = db_file.stat()
                if stat.st_mtime < cutoff:
                    db_file.unlink()
                    wal_file = db_file.with_suffix(".db-wal")
                    shm_file = db_file.with_suffix(".db-shm")
                    if wal_file.exists():
                        wal_file.unlink()
                    if shm_file.exists():
                        shm_file.unlink()
                    removed += 1
                    logger.info("Cleaned up stale graph DB: %s", db_file.name)
            except OSError as exc:
                logger.debug("Failed to clean up %s: %s", db_file, exc)

        return removed

    def total_size_bytes(self) -> int:
        """Total disk usage of all graph databases."""
        if not self._graph_dir.exists():
            return 0

        total = 0
        for db_file in self._graph_dir.glob("*.db*"):
            try:
                total += db_file.stat().st_size
            except OSError:
                pass
        return total

    def delete_workspace(self, workspace_root: str) -> bool:
        """Delete the graph database for a specific workspace."""
        ws_hash = _workspace_hash(workspace_root)
        db_path = self._graph_dir / f"{ws_hash}.db"

        if not db_path.exists():
            return False

        try:
            db_path.unlink()
            for suffix in (".db-wal", ".db-shm"):
                extra = db_path.with_suffix(suffix)
                if extra.exists():
                    extra.unlink()
            return True
        except OSError as exc:
            logger.warning("Failed to delete workspace graph: %s", exc)
            return False


def _workspace_hash(workspace_root: str) -> str:
    return hashlib.sha256(workspace_root.encode()).hexdigest()[:16]
