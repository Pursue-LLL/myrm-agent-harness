"""File snapshot observer — captures pre-modification content for revert support.

Records original file content before each create/modify operation, enabling
message-level and file-level undo. Snapshots persist to disk for crash recovery.

Design choices:
- Registered FIRST in ObserverManager so it captures content before any other
  observer (e.g. FormatObserver) modifies the file.
- Per-session isolation prevents cross-session conflicts.
- 2 MB file-size cap and 50 MB total-store cap prevent memory/disk exhaustion.
- asyncio-safe: all dict mutations are synchronous between await points.

[INPUT]
- toolkits.code_execution.utils.workspace_path::WorkspacePathResolver (POS: Workspace path resolver with intelligent auto-detection.)

[OUTPUT]
- SnapshotOp: In-memory snapshot index with async disk persistence.
- FileSnapshot: class — File Snapshot
- SnapshotStore: class — Snapshot Store
- SnapshotObserver: class — Snapshot Observer
- set_current_message_id: Captures pre-modification file content for undo support.

[POS]
File snapshot observer — captures pre-modification content for revert support.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .base import FileOperationObserver

logger = logging.getLogger(__name__)

_persist_tasks: set[asyncio.Task[None]] = set()

MAX_FILE_BYTES: int = 2 * 1024 * 1024  # 2 MB
MAX_STORE_BYTES: int = 50 * 1024 * 1024  # 50 MB
SNAPSHOTS_DIR_NAME: str = ".myrm/snapshots"


class SnapshotOp(StrEnum):
    CREATE = "create"
    MODIFY = "modify"


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    path: str
    operation: SnapshotOp
    original_content: str | None
    timestamp: float = field(default_factory=time.time)

    @property
    def size_bytes(self) -> int:
        return len(self.original_content.encode("utf-8")) if self.original_content else 0


_snapshot_store_var: contextvars.ContextVar[SnapshotStore | None] = contextvars.ContextVar(
    "snapshot_store", default=None
)


class SnapshotStore:
    """In-memory snapshot index with async disk persistence.

    Structure: {session_id: {message_id: [FileSnapshot, ...]}}

    Uses ContextVar for per-context isolation (consistent with StalenessGuard
    and TaintTracker). Each asyncio Task / agent run gets its own store.
    """

    _lock: contextvars.ContextVar[asyncio.Lock | None] = contextvars.ContextVar("snapshot_store_lock", default=None)

    def __init__(self) -> None:
        self._store: dict[str, dict[str, list[FileSnapshot]]] = {}
        self._total_bytes: int = 0

    @classmethod
    def get(cls) -> SnapshotStore:
        store = _snapshot_store_var.get()
        if store is None:
            store = cls()
            _snapshot_store_var.set(store)
        return store

    @classmethod
    def reset(cls) -> None:
        _snapshot_store_var.set(None)

    def _get_lock(self) -> asyncio.Lock:
        lock = self._lock.get()
        if lock is None:
            lock = asyncio.Lock()
            self._lock.set(lock)
        return lock

    def record(self, session_id: str, message_id: str, snapshot: FileSnapshot) -> bool:
        """Record a snapshot. Returns False if size limits exceeded."""
        if snapshot.size_bytes > MAX_FILE_BYTES:
            logger.info(
                "Snapshot skipped (file too large): %s (%d bytes)",
                snapshot.path,
                snapshot.size_bytes,
            )
            return False

        if self._total_bytes + snapshot.size_bytes > MAX_STORE_BYTES:
            logger.warning(
                "Snapshot store full (%d bytes), skipping: %s",
                self._total_bytes,
                snapshot.path,
            )
            return False

        session = self._store.setdefault(session_id, {})
        msg_snapshots = session.setdefault(message_id, [])
        msg_snapshots.append(snapshot)
        self._total_bytes += snapshot.size_bytes
        return True

    def get_message_snapshots(self, session_id: str, message_id: str) -> list[FileSnapshot]:
        return self._store.get(session_id, {}).get(message_id, [])

    def get_session_snapshots(self, session_id: str) -> dict[str, list[FileSnapshot]]:
        return dict(self._store.get(session_id, {}))

    def get_file_snapshot(self, session_id: str, message_id: str, path: str) -> FileSnapshot | None:
        for snap in reversed(self.get_message_snapshots(session_id, message_id)):
            if snap.path == path:
                return snap
        return None

    def get_initial_file_snapshot(self, session_id: str, message_id: str, path: str) -> FileSnapshot | None:
        """获取当前回合（message_id）中该文件的第一次快照，用于计算累积 Diff。"""
        for snap in self.get_message_snapshots(session_id, message_id):
            if snap.path == path:
                return snap
        return None

    def remove_message(self, session_id: str, message_id: str) -> list[FileSnapshot]:
        session = self._store.get(session_id, {})
        removed = session.pop(message_id, [])
        for snap in removed:
            self._total_bytes -= snap.size_bytes
        return removed

    def clear_session(self, session_id: str) -> int:
        session = self._store.pop(session_id, {})
        count = 0
        for snapshots in session.values():
            for snap in snapshots:
                self._total_bytes -= snap.size_bytes
                count += 1
        return count

    async def remove_persisted_message(self, workspace_root: str, session_id: str, message_id: str) -> None:
        """Delete the on-disk snapshot file for a specific message."""
        target = Path(workspace_root) / SNAPSHOTS_DIR_NAME / session_id / f"{message_id}.json"
        try:
            if target.is_file():
                await asyncio.to_thread(target.unlink)
        except OSError:
            logger.warning("Failed to delete snapshot file: %s", target)

    async def clear_persisted_session(self, workspace_root: str, session_id: str) -> None:
        """Delete all on-disk snapshot files for a session."""
        session_dir = Path(workspace_root) / SNAPSHOTS_DIR_NAME / session_id
        try:
            if session_dir.is_dir():
                import shutil

                await asyncio.to_thread(shutil.rmtree, session_dir)
        except OSError:
            logger.warning("Failed to delete snapshot directory: %s", session_dir)

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    async def persist_to_disk(self, workspace_root: str, session_id: str, message_id: str) -> None:
        snapshots = self.get_message_snapshots(session_id, message_id)
        if not snapshots:
            return

        snapshots_dir = Path(workspace_root) / SNAPSHOTS_DIR_NAME / session_id
        try:
            snapshots_dir.mkdir(parents=True, exist_ok=True)

            target = snapshots_dir / f"{message_id}.json"
            data = [
                {
                    "path": s.path,
                    "operation": s.operation.value,
                    "original_content": s.original_content,
                    "timestamp": s.timestamp,
                }
                for s in snapshots
            ]
            payload = json.dumps(data, ensure_ascii=False)

            async with self._get_lock():
                await asyncio.to_thread(target.write_text, payload, "utf-8")
        except OSError:
            logger.warning(
                "Failed to persist snapshots to disk for session=%s msg=%s",
                session_id,
                message_id,
            )

    @classmethod
    async def load_from_disk(cls, workspace_root: str, session_id: str) -> list[tuple[str, list[FileSnapshot]]]:
        snapshots_dir = Path(workspace_root) / SNAPSHOTS_DIR_NAME / session_id
        if not snapshots_dir.is_dir():
            return []

        result: list[tuple[str, list[FileSnapshot]]] = []
        try:
            for entry in sorted(snapshots_dir.iterdir()):
                if entry.suffix != ".json":
                    continue
                message_id = entry.stem
                raw = json.loads(await asyncio.to_thread(entry.read_text, "utf-8"))
                snaps = [
                    FileSnapshot(
                        path=item["path"],
                        operation=SnapshotOp(item["operation"]),
                        original_content=item["original_content"],
                        timestamp=item["timestamp"],
                    )
                    for item in raw
                ]
                result.append((message_id, snaps))
        except (OSError, json.JSONDecodeError, KeyError):
            logger.warning("Failed to load snapshots from disk for session=%s", session_id)
        return result


def _get_session_id() -> str:
    """Extract session_id from current LangGraph context."""
    try:
        from myrm_agent_harness.agent.context_management.infra.session_lock import (
            get_current_chat_id,
        )

        chat_id = get_current_chat_id()
        return chat_id if chat_id else "default"
    except Exception:
        return "default"


_current_message_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("snapshot_message_id", default=None)


def set_current_message_id(msg_id: str) -> None:
    _current_message_id.set(msg_id)


def get_current_message_id() -> str:
    val = _current_message_id.get()
    if val is None:
        val = f"msg_{int(time.time() * 1000)}"
        _current_message_id.set(val)
    return val


class SnapshotObserver(FileOperationObserver):
    """Captures pre-modification file content for undo support.

    Must be registered FIRST in ObserverManager to capture original content
    before other observers (e.g. FormatObserver) modify the file.
    """

    async def on_file_created(self, path: str, content: str) -> None:
        session_id = _get_session_id()
        message_id = get_current_message_id()
        snap = FileSnapshot(path=path, operation=SnapshotOp.CREATE, original_content=None)
        store = SnapshotStore.get()
        store.record(session_id, message_id, snap)
        self._schedule_persist(store, session_id, message_id, path)

    async def on_file_modified(self, path: str, old_content: str, new_content: str) -> None:
        session_id = _get_session_id()
        message_id = get_current_message_id()
        snap = FileSnapshot(path=path, operation=SnapshotOp.MODIFY, original_content=old_content)
        store = SnapshotStore.get()
        store.record(session_id, message_id, snap)
        self._schedule_persist(store, session_id, message_id, path)

    async def on_file_viewed(self, path: str) -> None:
        pass

    @staticmethod
    def _schedule_persist(store: SnapshotStore, session_id: str, message_id: str, file_path: str) -> None:
        """Fire-and-forget disk persistence. Uses CWD as workspace root."""
        from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import (
            WorkspacePathResolver,
        )

        workspace_root = str(WorkspacePathResolver.resolve_workspace_root())
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(store.persist_to_disk(workspace_root, session_id, message_id))
            _persist_tasks.add(task)
            task.add_done_callback(_persist_tasks.discard)
        except RuntimeError:
            pass
