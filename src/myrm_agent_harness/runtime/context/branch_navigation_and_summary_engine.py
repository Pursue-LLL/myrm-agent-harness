"""Non-destructive branch navigation and exploration summary engine.

Manages leaf pointers over immutable conversation trees, generates structured
summaries for abandoned exploratory branches, and provides zero-copy projections
without truncating historical trajectory.
"""

from __future__ import annotations

import time
import uuid

from .tree_session_storage import TreeSessionStorage
from .tree_session_storage_types import (
    BranchSummaryRecord,
    TreeEntry,
    TreeEntryKind,
    TreeProjection,
)


class BranchNavigationAndSummaryEngine:
    """Engine orchestrating leaf pointer navigation and branch summary generation."""

    def __init__(self, storage: TreeSessionStorage) -> None:
        self._storage = storage
        self._current_leaf_id: str | None = None
        self._active_branch_tag: str | None = None
        self._summary_counter: int = 0

    @property
    def current_leaf_id(self) -> str | None:
        """Return the current active leaf entry ID."""
        return self._current_leaf_id

    @property
    def active_branch_tag(self) -> str | None:
        """Return the active branch tag."""
        return self._active_branch_tag

    def set_leaf_pointer(
        self,
        leaf_id: str,
        branch_tag: str | None = None,
    ) -> TreeProjection:
        """Directly position the leaf pointer at an existing entry."""
        if self._storage.get_entry(leaf_id) is None:
            raise KeyError(f"Target entry '{leaf_id}' does not exist in storage.")

        self._current_leaf_id = leaf_id
        if branch_tag is not None:
            self._active_branch_tag = branch_tag
        return self.project_current_view()

    def project_current_view(self) -> TreeProjection:
        """Generate a linearized view from root to current leaf."""
        if self._current_leaf_id is None:
            return TreeProjection(
                leaf_id="",
                path_entries=(),
                active_branch_tag=self._active_branch_tag,
                total_entries_count=0,
            )

        entries = self._storage.get_ancestor_path(self._current_leaf_id)
        return TreeProjection(
            leaf_id=self._current_leaf_id,
            path_entries=tuple(entries),
            active_branch_tag=self._active_branch_tag,
            total_entries_count=len(entries),
        )

    def navigate_to(
        self,
        target_entry_id: str,
        target_branch_tag: str | None = None,
        auto_summarize_abandoned: bool = True,
    ) -> tuple[TreeProjection, BranchSummaryRecord | None]:
        """Navigate the leaf pointer to target_entry_id, optionally summarizing abandoned path.

        If target_entry_id diverges from current_leaf_id and auto_summarize_abandoned is True,
        summarizes the divergent nodes on the abandoned branch and appends a summary entry.
        """
        target_entry = self._storage.get_entry(target_entry_id)
        if target_entry is None:
            raise KeyError(f"Navigation target '{target_entry_id}' not found.")

        summary_record: BranchSummaryRecord | None = None

        if (
            auto_summarize_abandoned
            and self._current_leaf_id is not None
            and self._current_leaf_id != target_entry_id
        ):
            divergent_nodes = list(
                self._storage.get_branch_divergence(
                    self._current_leaf_id, target_entry_id
                )
            )
            if divergent_nodes:
                lca = self._storage.find_lca(self._current_leaf_id, target_entry_id)
                fork_id = lca.entry_id if lca else target_entry_id
                summary_record = self._generate_branch_summary(
                    fork_point_id=fork_id,
                    abandoned_leaf_id=self._current_leaf_id,
                    abandoned_entries=divergent_nodes,
                )

                # Persist branch summary as an immutable entry attached to fork_id
                summary_entry_id = f"bsum_{uuid.uuid4().hex[:8]}"
                summary_tree_entry = TreeEntry(
                    entry_id=summary_entry_id,
                    parent_id=target_entry_id,
                    kind=TreeEntryKind.BRANCH_SUMMARY,
                    role="system",
                    content=summary_record.summary_text,
                    branch_tag=target_branch_tag or self._active_branch_tag,
                    metadata={
                        "summary_id": summary_record.summary_id,
                        "abandoned_leaf_id": summary_record.abandoned_leaf_id,
                        "abandoned_count": str(summary_record.abandoned_node_count),
                    },
                    created_at_ms=summary_record.created_at_ms,
                )
                self._storage.append_entry(summary_tree_entry)
                # Position leaf at the freshly attached branch summary node
                self._current_leaf_id = summary_entry_id
                if target_branch_tag is not None:
                    self._active_branch_tag = target_branch_tag
                return self.project_current_view(), summary_record

        self._current_leaf_id = target_entry_id
        if target_branch_tag is not None:
            self._active_branch_tag = target_branch_tag

        return self.project_current_view(), summary_record

    def fork_new_branch(
        self,
        from_entry_id: str,
        initial_content: str,
        role: str = "user",
        branch_tag: str | None = None,
        kind: TreeEntryKind = TreeEntryKind.MESSAGE,
    ) -> TreeEntry:
        """Fork a new branch from any historical entry without mutating existing branches."""
        if self._storage.get_entry(from_entry_id) is None:
            raise KeyError(f"Fork parent entry '{from_entry_id}' does not exist.")

        new_entry_id = f"fork_{uuid.uuid4().hex[:8]}"
        new_entry = TreeEntry(
            entry_id=new_entry_id,
            parent_id=from_entry_id,
            kind=kind,
            role=role,
            content=initial_content,
            branch_tag=branch_tag or f"branch_{uuid.uuid4().hex[:6]}",
            created_at_ms=int(time.time() * 1000),
        )
        self._storage.append_entry(new_entry)
        self._current_leaf_id = new_entry_id
        self._active_branch_tag = new_entry.branch_tag
        return new_entry

    def _generate_branch_summary(
        self,
        fork_point_id: str,
        abandoned_leaf_id: str,
        abandoned_entries: list[TreeEntry],
    ) -> BranchSummaryRecord:
        """Synthesize a structured summary of the abandoned exploratory path."""
        self._summary_counter += 1
        summary_id = f"sum_{self._summary_counter}_{uuid.uuid4().hex[:6]}"

        insights: list[str] = []
        for node in abandoned_entries:
            snippet = node.content.strip().replace("\n", " ")
            if len(snippet) > 80:
                snippet = snippet[:77] + "..."
            insights.append(f"[{node.role.upper()}]: {snippet}")

        lines = [
            f"=== Abandoned Branch Exploration Summary ({len(abandoned_entries)} nodes) ===",
            f"Fork Point: {fork_point_id} -> Abandoned Leaf: {abandoned_leaf_id}",
            "Key trajectory events:",
        ]
        lines.extend(f"- {item}" for item in insights)
        summary_text = "\n".join(lines)

        return BranchSummaryRecord(
            summary_id=summary_id,
            fork_point_id=fork_point_id,
            abandoned_leaf_id=abandoned_leaf_id,
            summary_text=summary_text,
            key_insights=tuple(insights),
            abandoned_node_count=len(abandoned_entries),
            created_at_ms=int(time.time() * 1000),
        )
