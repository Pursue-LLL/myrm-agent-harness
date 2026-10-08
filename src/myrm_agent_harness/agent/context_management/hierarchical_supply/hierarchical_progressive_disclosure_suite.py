"""End-to-end facade orchestrating hierarchical enterprise context abstraction and progressive disclosure supply.

[INPUT]
- Domain types: HierarchyLevel, HierarchyNode, HierarchyTree, ProgressiveDisclosureConfig, DisclosureExpansionResult, AssembledSupplyContext.
- Component engines: HierarchicalContextTreeBuilder, AdaptiveBranchFoldingSentry.

[OUTPUT]
- HierarchicalProgressiveDisclosureContextSupplySuite: Unified facade providing tree loading, progressive expansion, and assembled context supply.

[POS]
Main entry point in agent/context_management/hierarchical_supply implementing Qwen Office Enterprise Context supply pattern.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .adaptive_branch_folding_sentry import AdaptiveBranchFoldingSentry
from .hierarchical_context_tree_builder import HierarchicalContextTreeBuilder
from .hierarchical_supply_types import (
    AssembledSupplyContext,
    DisclosureExpansionResult,
    HierarchyLevel,
    HierarchyNode,
    HierarchyTree,
    ProgressiveDisclosureConfig,
)


class HierarchicalProgressiveDisclosureContextSupplySuite:
    """Unified enterprise context orchestrator providing progressive disclosure and adaptive branch folding."""

    def __init__(
        self,
        config: ProgressiveDisclosureConfig | None = None,
        sentry: AdaptiveBranchFoldingSentry | None = None,
        tree: HierarchyTree | None = None,
    ) -> None:
        self._config = config or ProgressiveDisclosureConfig()
        self._sentry = sentry or AdaptiveBranchFoldingSentry(self._config)
        self._tree = tree or HierarchyTree(root_node_ids=(), nodes={})

    @property
    def config(self) -> ProgressiveDisclosureConfig:
        return self._config

    @property
    def current_tree(self) -> HierarchyTree:
        return self._tree

    def load_tree(self, tree: HierarchyTree) -> None:
        """Loads and activates a new business context topology tree."""
        self._tree = tree

    def expand_business_context(
        self,
        node_id: str,
        target_level: HierarchyLevel | None = None,
    ) -> DisclosureExpansionResult:
        """Expands target node in active tree, enforcing L3 active ceilings and collapsing excess leaves."""
        if node_id not in self._tree.nodes:
            raise KeyError(f"Context node '{node_id}' does not exist in current hierarchy tree.")

        current_nodes = dict(self._tree.nodes)
        node = current_nodes[node_id]

        # Expand target node
        full_tokens = max(1, (len(node.full_content) + 3) // 4)
        tokens_added = full_tokens - node.token_estimate

        expanded_node = HierarchyNode(
            node_id=node.node_id,
            title=node.title,
            level=target_level or node.level,
            summary=node.summary,
            full_content=node.full_content,
            parent_id=node.parent_id,
            children_ids=node.children_ids,
            is_expanded=True,
            is_completed=node.is_completed,
            token_estimate=full_tokens,
        )
        current_nodes[node_id] = expanded_node

        temp_tree = HierarchyTree(
            root_node_ids=self._tree.root_node_ids,
            nodes=current_nodes,
        )

        # Enforce folding sentry over surplus active nodes
        self._tree, folded_nodes = self._sentry.enforce_folding_policy(
            temp_tree, just_expanded_node_id=node_id
        )

        return DisclosureExpansionResult(
            node_id=node_id,
            target_level=expanded_node.level,
            expanded_text=expanded_node.full_content,
            tokens_added=max(0, tokens_added),
            folded_nodes=folded_nodes,
        )

    def mark_branch_completed(
        self,
        node_id: str,
        conclusion: str | None = None,
    ) -> None:
        """Marks node as completed and triggers immediate folding via sentry."""
        self._tree = self._sentry.mark_completed_and_fold(
            self._tree, node_id=node_id, completion_conclusion=conclusion
        )

    def assemble_context(self) -> AssembledSupplyContext:
        """Assembles prompt payload structured across L1 Backbone, L2 Cohort, and L3 Details."""
        if not self._tree.nodes:
            return AssembledSupplyContext(
                assembled_prompt="",
                active_l1_count=0,
                active_l2_count=0,
                active_l3_count=0,
                total_tokens=0,
            )

        lines: list[str] = [
            "[HIERARCHICAL ENTERPRISE CONTEXT SUPPLY]",
            "Structured multi-tier context with progressive disclosure drill-down:\n",
        ]

        active_l1 = 0
        active_l2 = 0
        active_l3 = 0

        # Group by level
        l1_nodes: list[HierarchyNode] = []
        l2_nodes: list[HierarchyNode] = []
        l3_nodes: list[HierarchyNode] = []

        for node in self._tree.nodes.values():
            if node.level == HierarchyLevel.L1_BACKBONE:
                l1_nodes.append(node)
                if node.is_expanded:
                    active_l1 += 1
            elif node.level == HierarchyLevel.L2_COHORT:
                l2_nodes.append(node)
                if node.is_expanded:
                    active_l2 += 1
            else:
                l3_nodes.append(node)
                if node.is_expanded:
                    active_l3 += 1

        # 1. Render L1 Backbone
        if l1_nodes:
            lines.append("### Tier 1: Backbone Objectives & Core Entities")
            for n in l1_nodes:
                content = n.full_content if n.is_expanded else n.summary
                lines.append(f"**[{n.node_id}] {n.title}**\n{content}\n")

        # 2. Render L2 Cohort / Relations
        if l2_nodes:
            lines.append("### Tier 2: Relational Topology & Execution Steps")
            for n in l2_nodes:
                if n.is_expanded:
                    lines.append(f"**[{n.node_id}] {n.title} (EXPANDED)**\n{n.full_content}\n")
                else:
                    lines.append(
                        f"**[{n.node_id}] {n.title} (FOLDED)**\n{n.summary}\n"
                        f"*(Call expand_business_context('{n.node_id}') to view details)*\n"
                    )

        # 3. Render L3 Detail Leaf
        if l3_nodes:
            lines.append("### Tier 3: Granular Evidence & Transactional Records")
            for n in l3_nodes:
                if n.is_expanded:
                    lines.append(f"**[{n.node_id}] {n.title} (ACTIVE DETAIL)**\n{n.full_content}\n")
                else:
                    status_tag = "COMPLETED" if n.is_completed else "COLLAPSED"
                    lines.append(
                        f"**[{n.node_id}] {n.title} ({status_tag})**\n{n.summary}\n"
                    )

        prompt_str = "\n".join(lines)
        total_tokens = max(1, (len(prompt_str) + 3) // 4)

        return AssembledSupplyContext(
            assembled_prompt=prompt_str,
            active_l1_count=active_l1,
            active_l2_count=active_l2,
            active_l3_count=active_l3,
            total_tokens=total_tokens,
        )

    @staticmethod
    def get_tool_definition() -> dict[str, str | dict[str, str | dict[str, str]]]:
        """Returns JSON schema for expand_business_context meta-tool for LLM function calling."""
        return {
            "name": "expand_business_context",
            "description": "Progressively expands a folded enterprise context node (Tier 2 Cohort or Tier 3 Detail) into full visibility.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "Unique identifier of the context node to unfold (e.g., 'cohort_campaign_a', 'invoice_rec_9921').",
                    },
                },
                "required": ["node_id"],
            },
        }
