# [INPUT]: HierarchyLevel, HierarchyNode, HierarchyTree, ProgressiveDisclosureConfig
# [OUTPUT]: AdaptiveBranchFoldingSentry
# [POS]: agent/context_management/hierarchical_supply/adaptive_branch_folding_sentry.py

"""Adaptive branch folding sentry managing active L3 detail ceilings and collapsing completed branches.

[INPUT]
- HierarchyLevel: Tier levels.
- HierarchyNode, HierarchyTree: Context nodes and topology tree.
- ProgressiveDisclosureConfig: Active L3 node thresholds and auto-folding policies.

[OUTPUT]
- AdaptiveBranchFoldingSentry: State monitor collapsing stale or completed branches to prevent context bloat.

[POS]
Dynamic context governor and prompt cache protection layer in hierarchical context supply.
"""

from __future__ import annotations

from typing import Sequence

from .hierarchical_supply_types import (
    HierarchyLevel,
    HierarchyNode,
    HierarchyTree,
    ProgressiveDisclosureConfig,
)


class AdaptiveBranchFoldingSentry:
    """Monitors active detail branches and automatically collapses finished or surplus leaves."""

    def __init__(self, config: ProgressiveDisclosureConfig | None = None) -> None:
        self._config = config or ProgressiveDisclosureConfig()

    def enforce_folding_policy(
        self,
        tree: HierarchyTree,
        just_expanded_node_id: str | None = None,
    ) -> tuple[HierarchyTree, Sequence[str]]:
        """Audits expanded L3 detail nodes against max_active_l3_nodes and collapses surplus nodes."""
        current_nodes = dict(tree.nodes)
        expanded_l3_ids = [
            nid
            for nid, node in current_nodes.items()
            if node.level == HierarchyLevel.L3_DETAIL and node.is_expanded
        ]

        folded_ids: list[str] = []

        # 1. First, collapse any completed nodes if auto_fold_completed_branches is active
        if self._config.auto_fold_completed_branches:
            for nid in list(expanded_l3_ids):
                node = current_nodes[nid]
                if node.is_completed and nid != just_expanded_node_id:
                    current_nodes[nid] = self._collapse_node(node)
                    expanded_l3_ids.remove(nid)
                    folded_ids.append(nid)

        # 2. If active L3 count still exceeds budget, collapse oldest nodes (excluding just expanded)
        max_cap = self._config.max_active_l3_nodes
        while len(expanded_l3_ids) > max_cap:
            candidate_id: str | None = None
            for nid in expanded_l3_ids:
                if nid != just_expanded_node_id:
                    candidate_id = nid
                    break

            if candidate_id is None:
                # Fallback: if all nodes match just_expanded_node_id, pick first
                candidate_id = expanded_l3_ids[0]

            node = current_nodes[candidate_id]
            current_nodes[candidate_id] = self._collapse_node(node)
            expanded_l3_ids.remove(candidate_id)
            folded_ids.append(candidate_id)

        updated_tree = HierarchyTree(
            root_node_ids=tree.root_node_ids,
            nodes=current_nodes,
        )
        return updated_tree, tuple(folded_ids)

    def mark_completed_and_fold(
        self,
        tree: HierarchyTree,
        node_id: str,
        completion_conclusion: str | None = None,
    ) -> HierarchyTree:
        """Marks a branch node as completed, appends conclusion to summary, and collapses it."""
        if node_id not in tree.nodes:
            return tree

        current_nodes = dict(tree.nodes)
        target = current_nodes[node_id]

        new_summary = target.summary
        if completion_conclusion:
            new_summary = f"{target.summary}\n[Completed Conclusion]: {completion_conclusion.strip()}"

        est_tokens = max(1, (len(new_summary) + 3) // 4)
        collapsed_completed = HierarchyNode(
            node_id=target.node_id,
            title=target.title,
            level=target.level,
            summary=new_summary,
            full_content=target.full_content,
            parent_id=target.parent_id,
            children_ids=target.children_ids,
            is_expanded=False,
            is_completed=True,
            token_estimate=est_tokens,
        )
        current_nodes[node_id] = collapsed_completed

        return HierarchyTree(root_node_ids=tree.root_node_ids, nodes=current_nodes)

    @staticmethod
    def _collapse_node(node: HierarchyNode) -> HierarchyNode:
        """Returns a copy of node with is_expanded=False and token cost reset to summary size."""
        tokens = max(1, (len(node.summary) + 3) // 4)
        return HierarchyNode(
            node_id=node.node_id,
            title=node.title,
            level=node.level,
            summary=node.summary,
            full_content=node.full_content,
            parent_id=node.parent_id,
            children_ids=node.children_ids,
            is_expanded=False,
            is_completed=node.is_completed,
            token_estimate=tokens,
        )
