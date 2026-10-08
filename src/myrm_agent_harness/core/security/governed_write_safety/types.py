"""
[POS] src/myrm_agent_harness/core/security/governed_write_safety/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] WriteProposalStatus, PreImageSnapshot, GovernedWriteProposal, ConflictRecoveryBundle, CommitWriteResult
Domain types for String-Is-Never-Authority Governed Write Safety Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WriteProposalStatus(StrEnum):
    """Lifecycle status of a governed write proposal."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    STALE_REJECTED = "stale_rejected"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class PreImageSnapshot:
    """Pre-write snapshot recording prior content before any disk mutation."""

    snapshot_id: str
    opaque_file_id: str
    raw_path: str
    content_sha256: str
    timestamp: float
    content_preview: str


@dataclass(frozen=True)
class GovernedWriteProposal:
    """Proposal binding run context, opaque ID, base pre-image, and candidate content."""

    proposal_id: str
    opaque_file_id: str
    raw_path: str
    base_content_hash: str
    candidate_content_hash: str
    candidate_content: str
    status: WriteProposalStatus
    lease_token: str | None = None
    created_at: float = 0.0


@dataclass(frozen=True)
class ConflictRecoveryBundle:
    """Diagnostic and recovery payload generated when concurrent edit conflicts occur."""

    proposal_id: str
    opaque_file_id: str
    expected_base_hash: str
    actual_disk_hash: str
    reason: str
    suggested_action: str = "review_concurrent_changes_or_rebase"


@dataclass(frozen=True)
class CommitWriteResult:
    """Outcome of attempting to commit an approved governed write proposal."""

    success: bool
    proposal_id: str
    status: WriteProposalStatus
    pre_image_snapshot_id: str | None = None
    verified_disk_hash: str | None = None
    error_message: str | None = None
    conflict_bundle: ConflictRecoveryBundle | None = None
