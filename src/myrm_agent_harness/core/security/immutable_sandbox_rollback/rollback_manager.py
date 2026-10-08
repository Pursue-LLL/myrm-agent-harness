"""Atomic sandbox checkpoint and zero-cost environment rollback manager."""

from __future__ import annotations

import hashlib
import logging
import secrets
import time

from myrm_agent_harness.core.security.immutable_sandbox_rollback.types import (
    RollbackResult,
    SandboxCheckpoint,
)

logger = logging.getLogger(__name__)


class SandboxAtomicRollbackManager:
    """Manages immutable checkpoints and zero-blast-radius rollbacks for sandboxes."""

    def __init__(self) -> None:
        # Key: sandbox_id -> list of SandboxCheckpoint ordered chronologically
        self._checkpoints: dict[str, list[SandboxCheckpoint]] = {}

    @staticmethod
    def compute_manifest_digest(file_manifest: dict[str, str]) -> str:
        """Compute deterministic canonical digest of a file manifest (path -> hash)."""
        hasher = hashlib.sha256()
        for path in sorted(file_manifest.keys()):
            hasher.update(path.encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(file_manifest[path].encode("utf-8"))
            hasher.update(b"\x00")
        return hasher.hexdigest()

    def create_checkpoint(
        self,
        sandbox_id: str,
        description: str,
        file_manifest: dict[str, str],
    ) -> SandboxCheckpoint:
        """Create an atomic snapshot checkpoint for a sandbox environment."""
        checkpoint_id = f"chk-{secrets.token_hex(8)}"
        digest = self.compute_manifest_digest(file_manifest)
        now = time.time()

        checkpoint = SandboxCheckpoint(
            checkpoint_id=checkpoint_id,
            sandbox_id=sandbox_id,
            created_at=now,
            description=description,
            workspace_state_digest=digest,
            file_manifest=dict(file_manifest),
        )

        if sandbox_id not in self._checkpoints:
            self._checkpoints[sandbox_id] = []
        self._checkpoints[sandbox_id].append(checkpoint)

        logger.info(
            "Created atomic checkpoint '%s' for sandbox '%s' with %d files.",
            checkpoint_id,
            sandbox_id,
            len(file_manifest),
        )
        return checkpoint

    def list_checkpoints(self, sandbox_id: str) -> list[SandboxCheckpoint]:
        """List all snapshots registered for a sandbox."""
        return list(self._checkpoints.get(sandbox_id, []))

    def get_checkpoint(self, sandbox_id: str, checkpoint_id: str) -> SandboxCheckpoint | None:
        """Retrieve a specific checkpoint by ID."""
        for chk in self._checkpoints.get(sandbox_id, []):
            if chk.checkpoint_id == checkpoint_id:
                return chk
        return None

    def rollback_to_checkpoint(
        self,
        sandbox_id: str,
        checkpoint_id: str,
        current_manifest: dict[str, str],
    ) -> tuple[RollbackResult, dict[str, str]]:
        """Rollback sandbox files to the exact state saved in checkpoint.

        Returns:
            Tuple of (RollbackResult, restored_file_manifest).
        """
        target = self.get_checkpoint(sandbox_id, checkpoint_id)
        if target is None:
            res = RollbackResult(
                success=False,
                checkpoint_id=checkpoint_id,
                restored_files_count=0,
                pruned_files_count=0,
                restored_at=time.time(),
                error_message=f"Checkpoint '{checkpoint_id}' not found for sandbox '{sandbox_id}'.",
            )
            return (res, current_manifest)

        # Calculate diff
        restored_files_count = 0
        pruned_files_count = 0

        # Files in target checkpoint that were changed or missing in current
        for path, target_hash in target.file_manifest.items():
            if path not in current_manifest or current_manifest[path] != target_hash:
                restored_files_count += 1

        # Files created after checkpoint that must be pruned
        for path in current_manifest:
            if path not in target.file_manifest:
                pruned_files_count += 1

        res = RollbackResult(
            success=True,
            checkpoint_id=checkpoint_id,
            restored_files_count=restored_files_count,
            pruned_files_count=pruned_files_count,
            restored_at=time.time(),
            error_message=None,
        )

        return (res, dict(target.file_manifest))
