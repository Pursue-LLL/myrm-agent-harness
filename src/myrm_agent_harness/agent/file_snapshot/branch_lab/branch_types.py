"""Data types and schemas for zero-copy sandbox branch lab.

[INPUT]
None. Standalone type definitions for branch management and CAS/COW tracking.

[OUTPUT]
BranchStatus, BranchVerdict, MutationType, BranchMutation, BranchDescriptor,
BranchDiffItem, BranchDiffSummary, BranchLabReceipt, BranchPromoteResult,
BranchDiscardResult, BranchLabConfig.

[POS]
Type definitions for zero-copy sandbox branch lab in file_snapshot.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import StrEnum


class BranchStatus(StrEnum):
    """Lifecycle status of a zero-copy experimental branch."""

    ACTIVE = "active"
    PROMOTED = "promoted"
    DISCARDED = "discarded"


class BranchVerdict(StrEnum):
    """Evaluation verdict matching benchmark report contracts."""

    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"
    UNAVAILABLE = "UNAVAILABLE"
    DISCARDED = "DISCARDED"
    PROMOTED = "PROMOTED"


class MutationType(StrEnum):
    """File mutation category within a copy-on-write branch overlay."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class BranchMutation:
    """Record of a single file mutation in a branch overlay."""

    file_path: str
    mutation_type: MutationType
    content_hash: str
    byte_size: int
    old_size: int | None = None


@dataclass(frozen=True, slots=True)
class BranchDescriptor:
    """Metadata describing an isolated zero-copy branch."""

    branch_id: str
    branch_name: str
    base_snapshot_id: str
    status: BranchStatus
    created_at: float
    closed_at: float | None = None
    purpose: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BranchDiffItem:
    """Diff detail for a single file between branch and base snapshot."""

    path: str
    change_type: MutationType
    old_hash: str | None
    new_hash: str | None
    delta_bytes: int


@dataclass(frozen=True, slots=True)
class BranchDiffSummary:
    """Summary of all changes on a branch compared to its base snapshot."""

    branch_id: str
    base_snapshot_id: str
    total_changes: int
    files_added: int
    files_modified: int
    files_deleted: int
    delta_bytes_total: int
    items: list[BranchDiffItem] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BranchLabReceipt:
    """Immutable audit receipt conforming to benchmark report discipline."""

    receipt_id: str
    branch_id: str
    base_snapshot_id: str
    verdict: BranchVerdict
    wall_time_ms: float
    files_changed: int
    delta_bytes: int
    immutable_hash: str
    timestamp: float

    @classmethod
    def generate(
        cls,
        branch_id: str,
        base_snapshot_id: str,
        verdict: BranchVerdict,
        wall_time_ms: float,
        files_changed: int,
        delta_bytes: int,
    ) -> BranchLabReceipt:
        """Create an immutable receipt with a deterministic sha256 fingerprint."""
        now = time.time()
        raw_sig = (
            f"{branch_id}:{base_snapshot_id}:{verdict.value}:{wall_time_ms:.2f}:"
            f"{files_changed}:{delta_bytes}:{now:.4f}"
        )
        immutable_hash = hashlib.sha256(raw_sig.encode("utf-8")).hexdigest()
        receipt_id = f"rcpt_{immutable_hash[:16]}"
        return cls(
            receipt_id=receipt_id,
            branch_id=branch_id,
            base_snapshot_id=base_snapshot_id,
            verdict=verdict,
            wall_time_ms=wall_time_ms,
            files_changed=files_changed,
            delta_bytes=delta_bytes,
            immutable_hash=immutable_hash,
            timestamp=now,
        )


@dataclass(frozen=True, slots=True)
class BranchPromoteResult:
    """Outcome of promoting a winning branch to the main workspace timeline."""

    success: bool
    branch_id: str
    base_snapshot_id: str
    promoted_snapshot_id: str | None
    files_applied: int
    total_bytes_applied: int
    receipt: BranchLabReceipt
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BranchDiscardResult:
    """Outcome of discarding a failed or speculative experimental branch."""

    success: bool
    branch_id: str
    bytes_reclaimed: int
    reason: str
    receipt: BranchLabReceipt


@dataclass(frozen=True, slots=True)
class BranchLabConfig:
    """Operational settings for zero-copy branch experiment labs."""

    max_active_branches: int = 10
    max_branch_delta_bytes: int = 104_857_600  # 100 MB per branch
    auto_prune_discarded: bool = True
