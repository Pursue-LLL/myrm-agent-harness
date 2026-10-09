"""Lifecycle and rollout manager for zero-copy sandbox experimental branches.

[INPUT]
Base snapshot IDs, file mutation requests, promotion/discard decisions.

[OUTPUT]
ZeroCopyBranchManager implementing fork, mutate, diff, discard, and promote flows.

[POS]
Core branch orchestration engine inside file_snapshot/branch_lab.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from .branch_cas_overlay import BranchCasOverlay
from .branch_types import (
    BranchDescriptor,
    BranchDiffItem,
    BranchDiffSummary,
    BranchDiscardResult,
    BranchLabConfig,
    BranchLabReceipt,
    BranchMutation,
    BranchPromoteResult,
    BranchStatus,
    BranchVerdict,
    MutationType,
)

logger = logging.getLogger(__name__)


class ZeroCopyBranchManager:
    """Manages zero-copy branches, mutation tracking, diffs, discard, and promotions."""

    def __init__(
        self,
        config: BranchLabConfig | None = None,
        overlay: BranchCasOverlay | None = None,
    ) -> None:
        self._config = config or BranchLabConfig()
        self._overlay = overlay or BranchCasOverlay()
        self._branches: dict[str, BranchDescriptor] = {}
        self._receipts: dict[str, BranchLabReceipt] = {}

    def fork_branch(
        self,
        base_snapshot_id: str,
        branch_name: str = "",
        purpose: str = "",
        metadata: dict[str, str] | None = None,
    ) -> BranchDescriptor:
        """Fork an isolated zero-copy branch from an existing base snapshot ID."""
        if not base_snapshot_id or not base_snapshot_id.strip():
            raise ValueError("base_snapshot_id must be a non-empty identifier")

        active_count = len(self.list_active_branches())
        if active_count >= self._config.max_active_branches:
            raise RuntimeError(
                f"Active branches limit reached ({active_count}/{self._config.max_active_branches})"
            )

        branch_id = f"br_{uuid.uuid4().hex[:12]}"
        now = time.time()
        descriptor = BranchDescriptor(
            branch_id=branch_id,
            branch_name=branch_name or f"branch-{branch_id[3:9]}",
            base_snapshot_id=base_snapshot_id,
            status=BranchStatus.ACTIVE,
            created_at=now,
            purpose=purpose,
            metadata=dict(metadata or {}),
        )
        self._branches[branch_id] = descriptor
        logger.info("Forked zero-copy branch %s from base %s", branch_id, base_snapshot_id)
        return descriptor

    def record_mutation(
        self,
        branch_id: str,
        file_path: str,
        mutation_type: MutationType,
        content: bytes | None = None,
        old_size: int | None = None,
    ) -> BranchMutation:
        """Record a file mutation on the specified active branch."""
        branch = self.get_branch(branch_id)
        if branch is None or branch.status != BranchStatus.ACTIVE:
            raise ValueError(f"Branch {branch_id} is not active or does not exist")

        if mutation_type == MutationType.DELETED:
            return self._overlay.record_delete(branch_id, file_path, old_size=old_size)

        payload = content if content is not None else b""
        current_delta = self._overlay.calculate_branch_delta_bytes(branch_id)
        if current_delta + len(payload) > self._config.max_branch_delta_bytes:
            raise ValueError(
                f"Mutation exceeds branch delta storage budget "
                f"({current_delta + len(payload)} > {self._config.max_branch_delta_bytes} bytes)"
            )

        return self._overlay.record_write(
            branch_id=branch_id,
            file_path=file_path,
            content=payload,
            old_size=old_size,
        )

    def diff_branch(self, branch_id: str) -> BranchDiffSummary:
        """Compute the diff summary between the branch overlay and base snapshot."""
        branch = self.get_branch(branch_id)
        if branch is None:
            raise ValueError(f"Branch {branch_id} does not exist")

        mutations = self._overlay.get_branch_mutations(branch_id)
        items: list[BranchDiffItem] = []
        added = 0
        modified = 0
        deleted = 0
        total_delta = 0

        for m in mutations:
            if m.mutation_type == MutationType.ADDED:
                added += 1
                items.append(
                    BranchDiffItem(
                        path=m.file_path,
                        change_type=m.mutation_type,
                        old_hash=None,
                        new_hash=m.content_hash,
                        delta_bytes=m.byte_size,
                    )
                )
                total_delta += m.byte_size
            elif m.mutation_type == MutationType.MODIFIED:
                modified += 1
                items.append(
                    BranchDiffItem(
                        path=m.file_path,
                        change_type=m.mutation_type,
                        old_hash=None,
                        new_hash=m.content_hash,
                        delta_bytes=m.byte_size - (m.old_size or 0),
                    )
                )
                total_delta += m.byte_size
            elif m.mutation_type == MutationType.DELETED:
                deleted += 1
                items.append(
                    BranchDiffItem(
                        path=m.file_path,
                        change_type=m.mutation_type,
                        old_hash=None,
                        new_hash=None,
                        delta_bytes=-(m.old_size or 0),
                    )
                )

        return BranchDiffSummary(
            branch_id=branch_id,
            base_snapshot_id=branch.base_snapshot_id,
            total_changes=len(mutations),
            files_added=added,
            files_modified=modified,
            files_deleted=deleted,
            delta_bytes_total=total_delta,
            items=items,
        )

    def discard_branch(self, branch_id: str, reason: str = "discarded") -> BranchDiscardResult:
        """Discard a failed branch and reclaim all copy-on-write overlay storage."""
        branch = self.get_branch(branch_id)
        if branch is None or branch.status != BranchStatus.ACTIVE:
            raise ValueError(f"Branch {branch_id} is not active or does not exist")

        now = time.time()
        wall_time_ms = max(0.0, (now - branch.created_at) * 1000.0)
        mutations = self._overlay.get_branch_mutations(branch_id)
        delta_bytes = sum(m.byte_size for m in mutations)

        receipt = BranchLabReceipt.generate(
            branch_id=branch_id,
            base_snapshot_id=branch.base_snapshot_id,
            verdict=BranchVerdict.DISCARDED,
            wall_time_ms=wall_time_ms,
            files_changed=len(mutations),
            delta_bytes=delta_bytes,
        )
        self._receipts[branch_id] = receipt

        reclaimed = self._overlay.clear_branch_overlay(branch_id)
        self._branches[branch_id] = BranchDescriptor(
            branch_id=branch.branch_id,
            branch_name=branch.branch_name,
            base_snapshot_id=branch.base_snapshot_id,
            status=BranchStatus.DISCARDED,
            created_at=branch.created_at,
            closed_at=now,
            purpose=branch.purpose,
            metadata=dict(branch.metadata),
        )
        logger.info("Discarded branch %s, reclaimed %d bytes: %s", branch_id, reclaimed, reason)
        return BranchDiscardResult(
            success=True,
            branch_id=branch_id,
            bytes_reclaimed=reclaimed,
            reason=reason,
            receipt=receipt,
        )

    def promote_branch(
        self,
        branch_id: str,
        target_working_dir: Path | str | None = None,
        promotion_reason: str = "promoted",
    ) -> BranchPromoteResult:
        """Promote a winning branch, optionally applying mutations to target directory."""
        branch = self.get_branch(branch_id)
        if branch is None or branch.status != BranchStatus.ACTIVE:
            raise ValueError(f"Branch {branch_id} is not active or does not exist")

        now = time.time()
        wall_time_ms = max(0.0, (now - branch.created_at) * 1000.0)
        mutations = self._overlay.get_branch_mutations(branch_id)
        files_applied = 0
        bytes_applied = 0

        if target_working_dir is not None:
            work_dir = Path(target_working_dir).resolve()
            work_dir.mkdir(parents=True, exist_ok=True)

            for m in mutations:
                target_file = work_dir / m.file_path
                if m.mutation_type in (MutationType.ADDED, MutationType.MODIFIED):
                    content = self._overlay.get_file_content(branch_id, m.file_path)
                    if content is not None:
                        target_file.parent.mkdir(parents=True, exist_ok=True)
                        target_file.write_bytes(content)
                        files_applied += 1
                        bytes_applied += len(content)
                elif m.mutation_type == MutationType.DELETED:
                    if target_file.exists():
                        target_file.unlink()
                        files_applied += 1

        promoted_snapshot_id = f"snap_promoted_{branch_id}_{int(now)}"
        receipt = BranchLabReceipt.generate(
            branch_id=branch_id,
            base_snapshot_id=branch.base_snapshot_id,
            verdict=BranchVerdict.PROMOTED,
            wall_time_ms=wall_time_ms,
            files_changed=len(mutations),
            delta_bytes=sum(m.byte_size for m in mutations),
        )
        self._receipts[branch_id] = receipt

        self._branches[branch_id] = BranchDescriptor(
            branch_id=branch.branch_id,
            branch_name=branch.branch_name,
            base_snapshot_id=branch.base_snapshot_id,
            status=BranchStatus.PROMOTED,
            created_at=branch.created_at,
            closed_at=now,
            purpose=branch.purpose,
            metadata=dict(branch.metadata),
        )
        logger.info(
            "Promoted branch %s into timeline %s (%s)",
            branch_id,
            promoted_snapshot_id,
            promotion_reason,
        )
        return BranchPromoteResult(
            success=True,
            branch_id=branch_id,
            base_snapshot_id=branch.base_snapshot_id,
            promoted_snapshot_id=promoted_snapshot_id,
            files_applied=files_applied,
            total_bytes_applied=bytes_applied,
            receipt=receipt,
        )

    def get_branch(self, branch_id: str) -> BranchDescriptor | None:
        """Get branch metadata descriptor by identifier."""
        return self._branches.get(branch_id)

    def list_active_branches(self) -> list[BranchDescriptor]:
        """List all currently active zero-copy branches."""
        return [b for b in self._branches.values() if b.status == BranchStatus.ACTIVE]

    def get_receipt(self, branch_id: str) -> BranchLabReceipt | None:
        """Retrieve audit receipt for a completed or discarded branch."""
        return self._receipts.get(branch_id)
