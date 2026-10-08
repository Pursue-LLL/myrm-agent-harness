"""Main suite orchestrating branch switch workspace synchronization and shadow stash protection.

[INPUT]
- session_id: str identifier of session tree
- tree_suite: SessionTreeDagSuite logical exploration tree
- workspace_root: str path to sandbox workspace directory

[OUTPUT]
- BranchSwitchWorkspaceStashAndArtifactIntegritySuite: Main orchestrator for workspace shadow stash and branch switching.

[POS]
Main suite orchestrating branch switch workspace synchronization and shadow stash protection.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Dict, List, Optional, Set, Tuple

from ..session_tree_dag import SessionTreeDagSuite
from .shadow_stash_engine import ShadowStashEngine
from .workspace_stash_types import (
    BranchWorkspaceSnapshot,
    WorkspaceStashConflictWarning,
    WorkspaceStashReceipt,
)


class BranchSwitchWorkspaceStashAndArtifactIntegritySuite:
    """Orchestrates 1:1 synchronization between logical session branches and physical sandbox files."""

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._branch_snapshots: Dict[str, BranchWorkspaceSnapshot] = {}
        self._tracked_files: Dict[str, Set[str]] = {}
        self._stash_receipts: List[WorkspaceStashReceipt] = []

    @property
    def session_id(self) -> str:
        """Return session ID."""
        return self._session_id

    def register_modified_files(self, branch_name: str, relative_paths: List[str]) -> None:
        """Register files modified or created under branch_name for tracking."""
        if branch_name not in self._tracked_files:
            self._tracked_files[branch_name] = set()
        for p in relative_paths:
            self._tracked_files[branch_name].add(p)

    def stash_current_branch(
        self,
        workspace_root: str,
        branch_name: str,
    ) -> BranchWorkspaceSnapshot:
        """Capture active workspace changes on branch_name into shadow stash."""
        tracked = list(self._tracked_files.get(branch_name, set()))
        snapshot = ShadowStashEngine.capture_workspace_snapshot(
            workspace_root=workspace_root,
            session_id=self._session_id,
            branch_name=branch_name,
            relative_paths=tracked,
        )
        self._branch_snapshots[branch_name] = snapshot
        return snapshot

    def switch_branch_with_workspace_sync(
        self,
        tree_suite: SessionTreeDagSuite,
        workspace_root: str,
        source_branch: str,
        target_branch: str,
        force: bool = False,
    ) -> Tuple[BranchWorkspaceSnapshot, WorkspaceStashReceipt]:
        """Atomically stash source branch files, switch active tree head, and restore target files."""
        # 1. Stash current branch state
        source_snapshot = self.stash_current_branch(workspace_root, source_branch)

        # 2. Retrieve or initialize target branch snapshot
        target_snapshot = self._branch_snapshots.get(
            target_branch,
            BranchWorkspaceSnapshot(
                session_id=self._session_id,
                branch_name=target_branch,
                stashed_files={},
                snapshot_hash="",
                is_pristine=True,
            ),
        )

        # 3. Pre-flight conflict check
        conflicts = ShadowStashEngine.detect_dirty_conflicts(
            workspace_root=workspace_root,
            target_snapshot=target_snapshot,
            source_snapshot=source_snapshot,
        )
        if conflicts and not force:
            conflict_paths = ", ".join(c.relative_path for c in conflicts)
            raise RuntimeError(f"Workspace branch switch blocked by dirty conflicts on: {conflict_paths}")

        # 4. Switch logical session tree head
        tree_suite.switch_active_branch(target_branch)

        # 5. Apply target branch snapshot on disk, removing source-exclusive files
        source_tracked = list(self._tracked_files.get(source_branch, set()))
        restored_count = ShadowStashEngine.apply_workspace_snapshot(
            workspace_root=workspace_root,
            target_snapshot=target_snapshot,
            previous_tracked_paths=source_tracked,
        )

        # 6. Issue synchronization receipt
        sync_hash = hashlib.sha256(
            f"{self._session_id}:{source_branch}:{target_branch}:{source_snapshot.snapshot_hash}:{target_snapshot.snapshot_hash}".encode("utf-8")
        ).hexdigest()[:16]

        receipt = WorkspaceStashReceipt(
            receipt_id=f"wsr_{uuid.uuid4().hex[:8]}",
            session_id=self._session_id,
            source_branch=source_branch,
            target_branch=target_branch,
            stashed_files_count=len(source_snapshot.stashed_files),
            restored_files_count=restored_count,
            conflicts_detected_count=len(conflicts),
            synchronization_hash=sync_hash,
        )
        self._stash_receipts.append(receipt)

        return target_snapshot, receipt

    def get_branch_snapshot(self, branch_name: str) -> Optional[BranchWorkspaceSnapshot]:
        """Fetch cached snapshot for branch."""
        return self._branch_snapshots.get(branch_name)

    def get_stash_receipts(self) -> List[WorkspaceStashReceipt]:
        """Retrieve all recorded synchronization receipts."""
        return list(self._stash_receipts)
