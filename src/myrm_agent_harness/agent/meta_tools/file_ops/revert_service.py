"""File revert service — undo AI file changes at message or file granularity.

Reads snapshots from SnapshotStore and restores files to their pre-modification
state. Integrates with FileIntegrityGuard (hash update) and ArtifactTracker (cleanup).

[INPUT]
- agent.context_management.tracking.artifact_tracker::ArtifactAction, (POS: Artifact Trail  Agent  Factory Research)
- toolkits.code_execution.utils.workspace_path::WorkspacePathResolver (POS: Workspace path resolver with intelligent auto-detection.)

[OUTPUT]
- RevertResult: Restores files to pre-AI-edit state.
- FileChange: class — File change descriptor (revertible + skip_reason).
- RevertService: class — Revert Service

[POS]
File revert service — undo AI file changes at message or file granularity.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .core.file_integrity_guard import get_file_integrity_guard
from .observers.snapshot_observer import FileSnapshot, SnapshotOp, SnapshotStore

logger = logging.getLogger(__name__)

_cleanup_tasks: set[asyncio.Task[None]] = set()


@dataclass(frozen=True, slots=True)
class RevertResult:
    reverted_files: list[str]
    warnings: list[str]
    skipped_files: list[str]


@dataclass(frozen=True, slots=True)
class FileChange:
    path: str
    operation: str
    has_original: bool
    timestamp: float
    revertible: bool = True
    skip_reason: str | None = None


def _snapshot_to_change(snap: FileSnapshot) -> FileChange:
    return FileChange(
        path=snap.path,
        operation=snap.operation.value,
        has_original=snap.original_content is not None,
        timestamp=snap.timestamp,
        revertible=snap.revertible,
        skip_reason=snap.skip_reason.value if snap.skip_reason is not None else None,
    )


class RevertService:
    """Restores files to pre-AI-edit state."""

    @staticmethod
    async def get_message_changes(session_id: str, message_id: str) -> list[FileChange]:
        store = SnapshotStore.get()
        snapshots = store.get_message_snapshots(session_id, message_id)
        return [_snapshot_to_change(s) for s in snapshots]

    @staticmethod
    async def get_session_changes(session_id: str) -> dict[str, list[FileChange]]:
        store = SnapshotStore.get()
        session_snaps = store.get_session_snapshots(session_id)
        result: dict[str, list[FileChange]] = {}
        for msg_id, snapshots in session_snaps.items():
            result[msg_id] = [_snapshot_to_change(s) for s in snapshots]
        return result

    @staticmethod
    async def revert_message(session_id: str, message_id: str, executor: object | None = None) -> RevertResult:
        """Revert all file changes from a specific message.

        Processes snapshots in reverse order to handle multiple edits to the
        same file correctly.
        """
        store = SnapshotStore.get()
        snapshots = store.get_message_snapshots(session_id, message_id)

        if not snapshots:
            return RevertResult(reverted_files=[], warnings=["No snapshots found for this message"], skipped_files=[])

        revertible_snaps = [s for s in snapshots if s.revertible]
        if not revertible_snaps:
            return RevertResult(
                reverted_files=[],
                warnings=["File changes cannot be reverted automatically"],
                skipped_files=[s.path for s in snapshots],
            )

        reverted: list[str] = []
        warnings: list[str] = []
        skipped: list[str] = []

        seen_paths: set[str] = set()

        for snap in reversed(revertible_snaps):
            if snap.path in seen_paths:
                continue
            seen_paths.add(snap.path)

            result = await _revert_single(snap, executor)
            if result.success:
                reverted.append(snap.path)
            elif result.warning:
                warnings.append(result.warning)
                skipped.append(snap.path)

        store.remove_message(session_id, message_id)
        _schedule_disk_cleanup(store, "message", session_id, message_id)
        return RevertResult(reverted_files=reverted, warnings=warnings, skipped_files=skipped)

    @staticmethod
    async def revert_file(
        session_id: str, message_id: str, file_path: str, executor: object | None = None
    ) -> RevertResult:
        """Revert a single file change from a specific message."""
        store = SnapshotStore.get()
        snap = store.get_file_snapshot(session_id, message_id, file_path)

        if snap is None:
            return RevertResult(
                reverted_files=[],
                warnings=[f"No snapshot found for {file_path} in this message"],
                skipped_files=[file_path],
            )

        if not snap.revertible:
            return RevertResult(
                reverted_files=[],
                warnings=[f"Cannot revert {file_path}: change is not revertible"],
                skipped_files=[file_path],
            )

        result = await _revert_single(snap, executor)
        if result.success:
            return RevertResult(reverted_files=[file_path], warnings=[], skipped_files=[])
        return RevertResult(reverted_files=[], warnings=[result.warning or "Unknown error"], skipped_files=[file_path])

    @staticmethod
    async def revert_session(session_id: str, executor: object | None = None) -> RevertResult:
        """Revert all file changes in a session (processes newest first)."""
        store = SnapshotStore.get()
        session_snaps = store.get_session_snapshots(session_id)

        all_reverted: list[str] = []
        all_warnings: list[str] = []
        all_skipped: list[str] = []
        seen_paths: set[str] = set()

        for msg_id in reversed(list(session_snaps.keys())):
            for snap in reversed(session_snaps[msg_id]):
                if not snap.revertible:
                    continue
                if snap.path in seen_paths:
                    continue
                seen_paths.add(snap.path)

                result = await _revert_single(snap, executor)
                if result.success:
                    all_reverted.append(snap.path)
                elif result.warning:
                    all_warnings.append(result.warning)
                    all_skipped.append(snap.path)

        store.clear_session(session_id)
        _schedule_disk_cleanup(store, "session", session_id)
        return RevertResult(reverted_files=all_reverted, warnings=all_warnings, skipped_files=all_skipped)


@dataclass(frozen=True, slots=True)
class _SingleRevertResult:
    success: bool
    warning: str | None = None


async def _revert_single(snap: FileSnapshot, executor: object | None) -> _SingleRevertResult:
    """Revert a single file snapshot."""
    if not snap.revertible:
        return _SingleRevertResult(success=False, warning=f"Cannot revert {snap.path}: not revertible")

    try:
        path = Path(snap.path)

        if snap.operation == SnapshotOp.CREATE:
            if path.is_file():
                os.remove(snap.path)
                logger.info("Reverted (deleted created file): %s", snap.path)
            return _SingleRevertResult(success=True)

        if snap.original_content is None:
            return _SingleRevertResult(success=False, warning=f"No original content for {snap.path}")

        if not path.exists():
            return _SingleRevertResult(success=False, warning=f"File no longer exists: {snap.path}. Cannot revert.")

        current_content = path.read_text("utf-8")
        if current_content == snap.original_content:
            return _SingleRevertResult(success=True)

        path.write_text(snap.original_content, "utf-8")

        guard = get_file_integrity_guard(executor)
        if guard is not None:
            guard.record_write(snap.path, snap.original_content)

        _cleanup_artifact(snap.path)

        logger.info("Reverted file: %s", snap.path)
        return _SingleRevertResult(success=True)

    except OSError as e:
        return _SingleRevertResult(success=False, warning=f"I/O error reverting {snap.path}: {e}")


def _cleanup_artifact(path: str) -> None:
    """Remove artifact tracking for a reverted file."""
    try:
        from myrm_agent_harness.agent.context_management.infra.session_lock import get_current_chat_id
        from myrm_agent_harness.agent.context_management.tracking.artifact_tracker import (
            ArtifactAction,
            ArtifactTracker,
        )

        chat_id = get_current_chat_id()
        if chat_id:
            ArtifactTracker.global_tracker().record(chat_id, path, ArtifactAction.DELETED, "Reverted by user")
    except Exception:
        pass


def _schedule_disk_cleanup(store: SnapshotStore, scope: str, session_id: str, message_id: str | None = None) -> None:
    """Fire-and-forget disk cleanup after revert."""
    from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import WorkspacePathResolver

    workspace_root = str(WorkspacePathResolver.resolve_workspace_root())
    try:
        loop = asyncio.get_running_loop()
        if scope == "message" and message_id:
            task = loop.create_task(store.remove_persisted_message(workspace_root, session_id, message_id))
        else:
            task = loop.create_task(store.clear_persisted_session(workspace_root, session_id))
        _cleanup_tasks.add(task)
        task.add_done_callback(_cleanup_tasks.discard)
    except RuntimeError:
        pass
