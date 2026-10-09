"""Unified suite facade for sandbox zero-copy branch lab and rollout promotions.

[INPUT]
Branch lifecycle commands, mutation requests, promotion/discard decisions.

[OUTPUT]
SandboxZeroCopyBranchLabSuite facade coordinating zero-copy branch lab operations.

[POS]
Top-level facade inside file_snapshot/branch_lab.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from .branch_cas_overlay import BranchCasOverlay
from .branch_types import (
    BranchDescriptor,
    BranchDiffSummary,
    BranchDiscardResult,
    BranchLabConfig,
    BranchLabReceipt,
    BranchMutation,
    BranchPromoteResult,
    MutationType,
)
from .zero_copy_branch_manager import ZeroCopyBranchManager

logger = logging.getLogger(__name__)


class SandboxZeroCopyBranchLabSuite:
    """High-level suite for zero-copy branch experimentation and parallel rollouts."""

    def __init__(
        self,
        config: BranchLabConfig | None = None,
        manager: ZeroCopyBranchManager | None = None,
    ) -> None:
        self._config = config or BranchLabConfig()
        if manager is not None:
            self._manager = manager
        else:
            overlay = BranchCasOverlay()
            self._manager = ZeroCopyBranchManager(config=self._config, overlay=overlay)

    @property
    def config(self) -> BranchLabConfig:
        """Access operational configuration."""
        return self._config

    def fork_branch(
        self,
        base_snapshot_id: str,
        branch_name: str = "",
        purpose: str = "",
        metadata: dict[str, str] | None = None,
    ) -> BranchDescriptor:
        """Fork an isolated zero-copy branch from an arbitrary base snapshot ID."""
        return self._manager.fork_branch(
            base_snapshot_id=base_snapshot_id,
            branch_name=branch_name,
            purpose=purpose,
            metadata=metadata,
        )

    def record_mutation(
        self,
        branch_id: str,
        file_path: str,
        mutation_type: MutationType,
        content: bytes | None = None,
        old_size: int | None = None,
    ) -> BranchMutation:
        """Record a file mutation on the specified active branch."""
        return self._manager.record_mutation(
            branch_id=branch_id,
            file_path=file_path,
            mutation_type=mutation_type,
            content=content,
            old_size=old_size,
        )

    def record_write_text(
        self,
        branch_id: str,
        file_path: str,
        text: str,
        old_size: int | None = None,
        encoding: str = "utf-8",
    ) -> BranchMutation:
        """Convenience method to record a text file write into the branch overlay."""
        return self.record_mutation(
            branch_id=branch_id,
            file_path=file_path,
            mutation_type=MutationType.MODIFIED if old_size else MutationType.ADDED,
            content=text.encode(encoding),
            old_size=old_size,
        )

    def diff_branch(self, branch_id: str) -> BranchDiffSummary:
        """Compute differences between the branch and its base snapshot."""
        return self._manager.diff_branch(branch_id)

    def discard_branch(self, branch_id: str, reason: str = "discarded") -> BranchDiscardResult:
        """Discard an experimental branch and release copy-on-write delta storage."""
        return self._manager.discard_branch(branch_id, reason=reason)

    def promote_branch(
        self,
        branch_id: str,
        target_working_dir: Path | str | None = None,
        promotion_reason: str = "promoted",
    ) -> BranchPromoteResult:
        """Promote a winning experimental branch into the main timeline."""
        return self._manager.promote_branch(
            branch_id=branch_id,
            target_working_dir=target_working_dir,
            promotion_reason=promotion_reason,
        )

    def get_branch(self, branch_id: str) -> BranchDescriptor | None:
        """Get branch metadata descriptor."""
        return self._manager.get_branch(branch_id)

    def list_active_branches(self) -> list[BranchDescriptor]:
        """List active branches."""
        return self._manager.list_active_branches()

    def get_receipt(self, branch_id: str) -> BranchLabReceipt | None:
        """Get benchmark receipt for a branch."""
        return self._manager.get_receipt(branch_id)

    def evaluate_and_promote_best(
        self,
        branch_ids: list[str],
        evaluator_fn: Callable[[BranchDiffSummary], float],
        target_working_dir: Path | str | None = None,
    ) -> tuple[BranchPromoteResult | None, list[BranchDiscardResult]]:
        """Evaluate multiple candidate branches, promote the highest scoring, and discard the rest.

        Args:
            branch_ids: Candidate branches to compare.
            evaluator_fn: Scoring function returning higher value for preferred candidate.
            target_working_dir: Destination working dir to apply the winning branch.

        Returns:
            Tuple of (winning promote result or None, list of discarded results).
        """
        if not branch_ids:
            return None, []

        scored_branches: list[tuple[float, str]] = []
        for bid in branch_ids:
            try:
                diff_summary = self.diff_branch(bid)
                score = evaluator_fn(diff_summary)
                scored_branches.append((score, bid))
            except Exception as exc:
                logger.warning("Failed to score branch %s: %s", bid, exc)
                scored_branches.append((float("-inf"), bid))

        scored_branches.sort(key=lambda x: x[0], reverse=True)
        winner_score, winner_id = scored_branches[0]

        promoted: BranchPromoteResult | None = None
        discards: list[BranchDiscardResult] = []

        if winner_score > float("-inf"):
            promoted = self.promote_branch(
                winner_id,
                target_working_dir=target_working_dir,
                promotion_reason=f"Winning rollout branch with score {winner_score:.2f}",
            )
            other_branches = [bid for _, bid in scored_branches[1:]]
        else:
            other_branches = [bid for _, bid in scored_branches]

        for bid in other_branches:
            res = self.discard_branch(bid, reason="Suboptimal candidate in parallel rollout")
            discards.append(res)

        return promoted, discards
