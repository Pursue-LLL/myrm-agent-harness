"""LCA branch exploration summary inheritance and cumulative file footprint engine.

Computes Lowest Common Ancestor (LCA) across session tree branches, extracts structured
exploration lessons from abandoned paths, and performs cumulative union aggregation
of file operations across branches and compactions.
Strict 0 Any, immutable contracts, single file <400 lines.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from .cumulative_file_tracker import CumulativeFileTracker
from .lca_branch_summary_types import (
    BranchExplorationSummary,
    BranchHandoffResult,
    CumulativeFileFootprint,
)
from .session_tree_navigator import (
    SessionEntryType,
    SessionTreeNodeEntry,
)

logger = logging.getLogger(__name__)


def find_lowest_common_ancestor(
    node_a_id: str,
    node_b_id: str,
    nodes_by_id: Mapping[str, SessionTreeNodeEntry],
) -> str | None:
    """Compute the Lowest Common Ancestor (LCA) of two nodes in an append-only tree.

    Returns the entry_id of the LCA, or None if they belong to disconnected forests.
    """
    if node_a_id == node_b_id:
        return node_a_id if node_a_id in nodes_by_id else None

    # Collect ancestors of node_a including itself
    ancestors_a: set[str] = set()
    curr_a: str | None = node_a_id
    visited_a: set[str] = set()

    while curr_a is not None and curr_a in nodes_by_id and curr_a not in visited_a:
        visited_a.add(curr_a)
        ancestors_a.add(curr_a)
        curr_a = nodes_by_id[curr_a].parent_id

    # Trace back from node_b to find the first common node in ancestors_a
    curr_b: str | None = node_b_id
    visited_b: set[str] = set()

    while curr_b is not None and curr_b in nodes_by_id and curr_b not in visited_b:
        visited_b.add(curr_b)
        if curr_b in ancestors_a:
            return curr_b
        curr_b = nodes_by_id[curr_b].parent_id

    return None


def collect_abandoned_path(
    source_leaf_id: str,
    lca_id: str | None,
    nodes_by_id: Mapping[str, SessionTreeNodeEntry],
) -> list[SessionTreeNodeEntry]:
    """Collect entries along the abandoned path from source_leaf_id up to (exclusive) lca_id."""
    abandoned: list[SessionTreeNodeEntry] = []
    curr: str | None = source_leaf_id
    visited: set[str] = set()

    while curr is not None and curr != lca_id and curr in nodes_by_id and curr not in visited:
        visited.add(curr)
        node = nodes_by_id[curr]
        abandoned.append(node)
        curr = node.parent_id

    abandoned.reverse()
    return abandoned


class LCABranchExplorationSummaryEngine:
    """Coordinates LCA calculation, branch exploration synthesis, and cumulative file tracking."""

    def __init__(self, initial_footprint: CumulativeFileFootprint | None = None) -> None:
        self._file_tracker = CumulativeFileTracker(initial_footprint)

    @property
    def file_tracker(self) -> CumulativeFileTracker:
        """Return the internal cumulative file tracker instance."""
        return self._file_tracker

    def synthesize_summary(
        self,
        abandoned_entries: Sequence[SessionTreeNodeEntry],
        *,
        source_leaf_id: str,
        target_node_id: str,
        lca_id: str | None,
        custom_goal: str | None = None,
        custom_lessons: Sequence[str] = (),
    ) -> BranchExplorationSummary:
        """Synthesize structured exploration insights from abandoned branch entries."""
        # Accumulate file reads and writes across the abandoned path
        self._file_tracker.accumulate_from_entries(abandoned_entries)
        cumulative_footprint = self._file_tracker.footprint

        # Extract semantic elements from abandoned entries
        goal_candidate = custom_goal or ""
        progress_items: list[str] = []
        decisions: list[str] = []
        lessons: list[str] = list(custom_lessons)
        leads: list[str] = []

        for entry in abandoned_entries:
            content = entry.content.strip()
            if not content:
                continue

            # Identify goals from initial user prompts or branch notes
            if not goal_candidate and (entry.role == "user" or "goal" in entry.details):
                goal_candidate = entry.details.get("goal") or content[:200]

            # Detect error messages or failure indications as negative lessons
            lower_content = content.lower()
            if any(k in lower_content for k in ("error:", "exception:", "traceback", "failed", "bug:")):
                summary_line = content.splitlines()[0][:150]
                lessons.append(f"Encountered error/pitfall: {summary_line}")

            # Capture tool executions or progress milestones
            if entry.entry_type == SessionEntryType.MESSAGE and entry.role == "assistant":
                if "tool_result" in lower_content or entry.details.get("tool_name"):
                    tool_desc = entry.details.get("tool_name", "tool")
                    progress_items.append(f"Executed exploration step with {tool_desc}")
                elif "decision" in lower_content:
                    decisions.append(content[:180])

        if not goal_candidate:
            goal_candidate = f"Exploratory branch rooted at LCA {lca_id or 'ROOT'}"

        return BranchExplorationSummary(
            goal=goal_candidate,
            progress_achieved=tuple(progress_items[:5]),
            key_decisions=tuple(decisions[:5]),
            pitfalls_and_lessons=tuple(lessons[:5]),
            abandoned_leads=tuple(leads[:5]),
            cumulative_files=cumulative_footprint,
            source_leaf_id=source_leaf_id,
            target_node_id=target_node_id,
            lca_node_id=lca_id,
            abandoned_entry_count=len(abandoned_entries),
        )

    def execute_branch_handoff(
        self,
        *,
        source_leaf_id: str,
        target_node_id: str,
        nodes_by_id: Mapping[str, SessionTreeNodeEntry],
        custom_goal: str | None = None,
        custom_lessons: Sequence[str] = (),
    ) -> BranchHandoffResult:
        """Execute complete LCA calculation, experience extraction, and cumulative file handoff."""
        if source_leaf_id == target_node_id:
            return BranchHandoffResult(
                source_leaf_id=source_leaf_id,
                target_node_id=target_node_id,
                lca_node_id=source_leaf_id,
                abandoned_entries_count=0,
                summary=None,
                inherited_cumulative_files=self._file_tracker.footprint,
                is_noop=True,
            )

        lca_id = find_lowest_common_ancestor(source_leaf_id, target_node_id, nodes_by_id)
        abandoned_entries = collect_abandoned_path(source_leaf_id, lca_id, nodes_by_id)

        summary: BranchExplorationSummary | None = None
        if abandoned_entries:
            summary = self.synthesize_summary(
                abandoned_entries,
                source_leaf_id=source_leaf_id,
                target_node_id=target_node_id,
                lca_id=lca_id,
                custom_goal=custom_goal,
                custom_lessons=custom_lessons,
            )

        return BranchHandoffResult(
            source_leaf_id=source_leaf_id,
            target_node_id=target_node_id,
            lca_node_id=lca_id,
            abandoned_entries_count=len(abandoned_entries),
            summary=summary,
            inherited_cumulative_files=self._file_tracker.footprint,
            is_noop=False,
        )

    @staticmethod
    def project_summary_to_context_block(
        summary: BranchExplorationSummary,
        *,
        prefix: str = "[PRIOR_BRANCH_EXPLORATION_EXPERIENCE]",
    ) -> str:
        """Render a formatted context block ready for injection into system or user prompt."""
        rendered_md = summary.render_markdown()
        return f"{prefix}\n{rendered_md}\n[END_PRIOR_BRANCH_EXPERIENCE]"
