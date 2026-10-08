"""Session Checkpoint and Workspace State Rollback Engine.

[POS] src/myrm_agent_harness/core/security/managed_permission_rollback/session_checkpoint_engine.py
[INPUT] myrm_agent_harness.core.security.managed_permission_rollback.types
[OUTPUT] SessionCheckpointRollbackEngine
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from typing import Final

from myrm_agent_harness.core.security.managed_permission_rollback.types import (
    EnterpriseRoleTemplate,
    FileStateSnapshot,
    RollbackDiffSummary,
    SessionCheckpoint,
)

logger: Final[logging.Logger] = logging.getLogger(__name__)


class SessionCheckpointRollbackEngine:
    """Engine orchestrating atomic session checkpoints and zero-loss workspace rollbacks."""

    def __init__(self) -> None:
        # Map: checkpoint_id -> SessionCheckpoint
        self._checkpoints: dict[str, SessionCheckpoint] = {}
        # Index: session_id -> list of checkpoint_ids in chronological order
        self._session_index: dict[str, list[str]] = {}

    def create_checkpoint(
        self,
        session_id: str,
        label: str,
        files: dict[str, bytes],
        memory_state: dict[str, str],
        active_role: EnterpriseRoleTemplate = EnterpriseRoleTemplate.SAFE_COLLABORATOR,
    ) -> SessionCheckpoint:
        """Capture an immutable atomic state snapshot of workspace files and conversational memory."""
        checkpoint_id = f"ckpt-{uuid.uuid4().hex[:12]}"
        now = time.time()

        file_snapshots: dict[str, FileStateSnapshot] = {}
        for path, content in files.items():
            content_hash = hashlib.sha256(content).hexdigest()
            file_snapshots[path] = FileStateSnapshot(
                relative_path=path,
                content_hash=content_hash,
                content_bytes=content,
            )

        checkpoint = SessionCheckpoint(
            checkpoint_id=checkpoint_id,
            session_id=session_id,
            label=label,
            created_at=now,
            file_snapshots=file_snapshots,
            memory_state=dict(memory_state),
            active_role=active_role,
        )

        self._checkpoints[checkpoint_id] = checkpoint
        self._session_index.setdefault(session_id, []).append(checkpoint_id)

        logger.info(
            "Created session checkpoint id=%s session=%s label='%s' (files=%d, memory_keys=%d)",
            checkpoint_id,
            session_id,
            label,
            len(file_snapshots),
            len(memory_state),
        )
        return checkpoint

    def get_checkpoint(self, checkpoint_id: str) -> SessionCheckpoint | None:
        """Fetch a specific checkpoint by ID."""
        return self._checkpoints.get(checkpoint_id)

    def list_checkpoints(self, session_id: str) -> list[SessionCheckpoint]:
        """List all historical checkpoints recorded for a specific session."""
        checkpoint_ids = self._session_index.get(session_id, [])
        return [
            self._checkpoints[cid]
            for cid in checkpoint_ids
            if cid in self._checkpoints
        ]

    def rollback_to_checkpoint(
        self,
        checkpoint_id: str,
        current_files: dict[str, bytes],
    ) -> tuple[RollbackDiffSummary, dict[str, bytes], dict[str, str]]:
        """Roll back workspace files and memory state to the targeted checkpoint.

        Returns:
            A tuple of (RollbackDiffSummary, restored_files, restored_memory_state).
        """
        checkpoint = self._checkpoints.get(checkpoint_id)
        if checkpoint is None:
            msg = f"Checkpoint '{checkpoint_id}' not found."
            raise KeyError(msg)

        # 1. Reconstruct restored file tree
        restored_files: dict[str, bytes] = {
            path: snap.content_bytes
            for path, snap in checkpoint.file_snapshots.items()
        }

        # 2. Compute diff between current_files and checkpoint
        modified_paths: list[str] = []

        # Check changed or reverted files
        for path, snap in checkpoint.file_snapshots.items():
            curr_bytes = current_files.get(path)
            if curr_bytes is None or hashlib.sha256(curr_bytes).hexdigest() != snap.content_hash:
                modified_paths.append(path)

        # Check files created after the checkpoint that should be dropped/reverted
        for curr_path in current_files:
            if curr_path not in checkpoint.file_snapshots and curr_path not in modified_paths:
                modified_paths.append(curr_path)

        diff_summary = RollbackDiffSummary(
            checkpoint_id=checkpoint_id,
            session_id=checkpoint.session_id,
            reverted_files_count=len(modified_paths),
            restored_memory_keys_count=len(checkpoint.memory_state),
            modified_paths=sorted(modified_paths),
            rolled_back_at=time.time(),
        )

        logger.info(
            "Rollback executed for session=%s to checkpoint=%s (reverted_files=%d)",
            checkpoint.session_id,
            checkpoint_id,
            len(modified_paths),
        )

        return diff_summary, restored_files, dict(checkpoint.memory_state)
