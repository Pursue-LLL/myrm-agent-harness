"""
[POS] src/myrm_agent_harness/core/security/governed_write_safety/governed_write_engine.py
[INPUT] hashlib, time, uuid, typing, types
[OUTPUT] GovernedWriteEngine
Governed write execution engine enforcing pre-image snapshots, stale rejection, and non-silent commits.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import Callable

from .types import (
    CommitWriteResult,
    ConflictRecoveryBundle,
    GovernedWriteProposal,
    PreImageSnapshot,
    WriteProposalStatus,
)

logger = logging.getLogger(__name__)


class GovernedWriteEngine:
    """Core engine enforcing 'string is never authority' and atomic governed write commitments."""

    def __init__(self) -> None:
        self._proposals: dict[str, GovernedWriteProposal] = {}
        self._snapshots: dict[str, PreImageSnapshot] = {}

    @staticmethod
    def _compute_sha256(content: str) -> str:
        """Compute hex SHA-256 digest of utf-8 content string."""
        return hashlib.sha256(content.encode()).hexdigest()

    def create_proposal(
        self,
        opaque_file_id: str,
        raw_path: str,
        current_disk_content: str,
        candidate_content: str,
    ) -> GovernedWriteProposal:
        """Create a new governed edit proposal bound to base pre-image and candidate hash."""
        pid = f"prop-w-{uuid.uuid4().hex[:10]}"
        base_hash = self._compute_sha256(current_disk_content)
        cand_hash = self._compute_sha256(candidate_content)

        proposal = GovernedWriteProposal(
            proposal_id=pid,
            opaque_file_id=opaque_file_id,
            raw_path=raw_path,
            base_content_hash=base_hash,
            candidate_content_hash=cand_hash,
            candidate_content=candidate_content,
            status=WriteProposalStatus.PROPOSED,
            lease_token=None,
            created_at=time.time(),
        )
        self._proposals[pid] = proposal
        logger.info(
            "Created governed write proposal %s for %s (base_hash=%s)",
            pid,
            opaque_file_id,
            base_hash[:8],
        )
        return proposal

    def approve_proposal(self, proposal_id: str) -> str:
        """Approve a proposal and issue a single-use write lease token."""
        if proposal_id not in self._proposals:
            raise KeyError(f"Proposal '{proposal_id}' does not exist")

        prop = self._proposals[proposal_id]
        if prop.status != WriteProposalStatus.PROPOSED:
            raise ValueError(
                f"Cannot approve proposal '{proposal_id}' in state '{prop.status.value}'"
            )

        token = f"lease-tok-{uuid.uuid4().hex[:12]}"
        approved = GovernedWriteProposal(
            proposal_id=prop.proposal_id,
            opaque_file_id=prop.opaque_file_id,
            raw_path=prop.raw_path,
            base_content_hash=prop.base_content_hash,
            candidate_content_hash=prop.candidate_content_hash,
            candidate_content=prop.candidate_content,
            status=WriteProposalStatus.APPROVED,
            lease_token=token,
            created_at=prop.created_at,
        )
        self._proposals[proposal_id] = approved
        logger.info("Approved proposal %s with write lease token", proposal_id)
        return token

    def commit_write(
        self,
        proposal_id: str,
        lease_token: str,
        current_disk_content: str,
        write_executor: Callable[[str], str],
    ) -> CommitWriteResult:
        """Execute atomic write with stale rejection, pre-image capture, and disk confirmation."""
        if proposal_id not in self._proposals:
            return CommitWriteResult(
                success=False,
                proposal_id=proposal_id,
                status=WriteProposalStatus.STALE_REJECTED,
                error_message=f"Proposal '{proposal_id}' not found",
            )

        prop = self._proposals[proposal_id]
        if prop.status != WriteProposalStatus.APPROVED or prop.lease_token != lease_token:
            return CommitWriteResult(
                success=False,
                proposal_id=proposal_id,
                status=prop.status,
                error_message="Invalid lease token or proposal is not approved for commit",
            )

        # 1. Stale check: Verify base pre-image against current disk content
        actual_disk_hash = self._compute_sha256(current_disk_content)
        if actual_disk_hash != prop.base_content_hash:
            # File was modified concurrently! Reject write to protect user work.
            conflict = ConflictRecoveryBundle(
                proposal_id=proposal_id,
                opaque_file_id=prop.opaque_file_id,
                expected_base_hash=prop.base_content_hash,
                actual_disk_hash=actual_disk_hash,
                reason="Concurrent modification detected: file on disk changed after proposal approval",
            )
            # Invalidate proposal state
            self._proposals[proposal_id] = GovernedWriteProposal(
                proposal_id=prop.proposal_id,
                opaque_file_id=prop.opaque_file_id,
                raw_path=prop.raw_path,
                base_content_hash=prop.base_content_hash,
                candidate_content_hash=prop.candidate_content_hash,
                candidate_content=prop.candidate_content,
                status=WriteProposalStatus.STALE_REJECTED,
                lease_token=None,
                created_at=prop.created_at,
            )
            logger.warning(
                "Stale write rejected for proposal %s on %s",
                proposal_id,
                prop.opaque_file_id,
            )
            return CommitWriteResult(
                success=False,
                proposal_id=proposal_id,
                status=WriteProposalStatus.STALE_REJECTED,
                error_message=conflict.reason,
                conflict_bundle=conflict,
            )

        # 2. Pre-image snapshot creation prior to disk mutation
        snap_id = f"snap-pre-{uuid.uuid4().hex[:10]}"
        snapshot = PreImageSnapshot(
            snapshot_id=snap_id,
            opaque_file_id=prop.opaque_file_id,
            raw_path=prop.raw_path,
            content_sha256=actual_disk_hash,
            timestamp=time.time(),
            content_preview=current_disk_content[:500],
        )
        self._snapshots[snap_id] = snapshot

        # 3. Perform write execution
        try:
            post_write_content = write_executor(prop.candidate_content)
        except Exception as e:
            logger.error("Write execution failed for %s: %s", proposal_id, e)
            return CommitWriteResult(
                success=False,
                proposal_id=proposal_id,
                status=WriteProposalStatus.APPROVED,
                pre_image_snapshot_id=snap_id,
                error_message=f"Write execution error: {e}",
            )

        # 4. Anti-overclaim verification: Check written content on disk
        post_write_hash = self._compute_sha256(post_write_content)
        if post_write_hash != prop.candidate_content_hash:
            logger.error(
                "Verification failure: written content hash %s != candidate hash %s",
                post_write_hash[:8],
                prop.candidate_content_hash[:8],
            )
            return CommitWriteResult(
                success=False,
                proposal_id=proposal_id,
                status=WriteProposalStatus.APPROVED,
                pre_image_snapshot_id=snap_id,
                error_message="Integrity check failed: written content does not match approved candidate",
            )

        # 5. Commit successful
        committed = GovernedWriteProposal(
            proposal_id=prop.proposal_id,
            opaque_file_id=prop.opaque_file_id,
            raw_path=prop.raw_path,
            base_content_hash=prop.base_content_hash,
            candidate_content_hash=prop.candidate_content_hash,
            candidate_content=prop.candidate_content,
            status=WriteProposalStatus.COMMITTED,
            lease_token=None,  # Consumed single-use token
            created_at=prop.created_at,
        )
        self._proposals[proposal_id] = committed
        logger.info(
            "Successfully committed governed write %s for %s",
            proposal_id,
            prop.opaque_file_id,
        )

        return CommitWriteResult(
            success=True,
            proposal_id=proposal_id,
            status=WriteProposalStatus.COMMITTED,
            pre_image_snapshot_id=snap_id,
            verified_disk_hash=post_write_hash,
        )

    def get_snapshot(self, snapshot_id: str) -> PreImageSnapshot | None:
        """Fetch pre-image snapshot record by ID."""
        return self._snapshots.get(snapshot_id)

    def get_proposal(self, proposal_id: str) -> GovernedWriteProposal | None:
        """Fetch governed proposal by ID."""
        return self._proposals.get(proposal_id)
