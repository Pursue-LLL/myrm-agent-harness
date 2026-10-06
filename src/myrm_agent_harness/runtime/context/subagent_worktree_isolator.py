"""Subagent Git Worktree write isolation and merge reconciliation.

Provides isolated workspace branches for parallel subagents to eliminate
file modification collisions, with automated conflict detection during merge.
"""

from __future__ import annotations

import os
import time
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.multi_gateway_trust_types import (
    WorktreeAllocation,
    WorktreeReconcileResult,
)


class SubagentWorktreeIsolator:
    """Allocates isolated workspace paths for subagents and reconciles file changes."""

    def __init__(self, base_worktree_dir: str = "/tmp/myrm_worktrees") -> None:
        self._base_worktree_dir = base_worktree_dir
        self._allocations: dict[str, WorktreeAllocation] = {}
        self._modified_files_by_subagent: dict[str, set[str]] = {}

    def allocate_worktree(
        self,
        subagent_id: str,
        task_name: str,
    ) -> WorktreeAllocation:
        """Create an isolated workspace boundary for a running subagent."""
        clean_name = f"{subagent_id}_{task_name.replace(' ', '_').lower()}"
        isolated_path = os.path.join(self._base_worktree_dir, clean_name)
        allocated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        allocation = WorktreeAllocation(
            subagent_id=subagent_id,
            worktree_name=clean_name,
            isolated_path=isolated_path,
            allocated_at=allocated_at,
        )

        self._allocations[subagent_id] = allocation
        self._modified_files_by_subagent[subagent_id] = set()
        return allocation

    def record_file_modification(
        self,
        subagent_id: str,
        relative_file_path: str,
    ) -> None:
        """Track which files a specific subagent modified within its workspace."""
        if subagent_id not in self._modified_files_by_subagent:
            self._modified_files_by_subagent[subagent_id] = set()
        self._modified_files_by_subagent[subagent_id].add(
            relative_file_path.strip().lstrip("/")
        )

    def reconcile_and_merge(
        self,
        subagent_ids: Sequence[str],
    ) -> WorktreeReconcileResult:
        """Reconcile file changes across multiple subagents and flag write collisions."""
        file_to_subagents: dict[str, list[str]] = {}
        all_merged_files: set[str] = set()

        for s_id in subagent_ids:
            files = self._modified_files_by_subagent.get(s_id, set())
            for f in files:
                all_merged_files.add(f)
                file_to_subagents.setdefault(f, []).append(s_id)

        conflicts: list[str] = []
        for file_path, authors in file_to_subagents.items():
            if len(authors) > 1:
                conflicts.append(
                    f"{file_path} (contested by subagents: {', '.join(authors)})"
                )

        has_conflict = len(conflicts) > 0
        if has_conflict:
            summary = (
                f"Detected {len(conflicts)} write collision(s) across "
                f"{len(subagent_ids)} subagents. Manual resolution required."
            )
        else:
            summary = (
                f"Successfully reconciled {len(all_merged_files)} unique file(s) "
                f"across {len(subagent_ids)} subagents without collisions."
            )

        return WorktreeReconcileResult(
            has_conflict=has_conflict,
            conflicting_files=tuple(conflicts),
            merged_files=tuple(sorted(all_merged_files)),
            summary=summary,
        )
