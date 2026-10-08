# [INPUT]: HierarchyLevel, HierarchyNode, HierarchyTree
# [OUTPUT]: HierarchicalContextTreeBuilder
# [POS]: agent/context_management/hierarchical_supply/hierarchical_context_tree_builder.py

"""Builder for compiling multi-tiered enterprise context into an indexed HierarchyTree.

[INPUT]
- HierarchyLevel: L1 Backbone, L2 Cohort, L3 Detail level enumeration.
- HierarchyNode, HierarchyTree: Output topology tree models.

[OUTPUT]
- HierarchicalContextTreeBuilder: Fluent declarative builder compiling hierarchical context nodes.

[POS]
Graph construction and validation layer for enterprise context supply.
"""

from __future__ import annotations

from typing import Sequence

from .hierarchical_supply_types import HierarchyLevel, HierarchyNode, HierarchyTree


class HierarchicalContextTreeBuilder:
    """Constructs and validates indexed HierarchyTree with bidirectional parent-child links."""

    def __init__(self) -> None:
        self._nodes: dict[str, HierarchyNode] = {}
        self._root_ids: list[str] = []

    def add_node(
        self,
        node_id: str,
        title: str,
        level: HierarchyLevel,
        summary: str,
        full_content: str,
        parent_id: str | None = None,
        is_expanded: bool | None = None,
        is_completed: bool = False,
    ) -> HierarchicalContextTreeBuilder:
        """Registers a contextual node with automatic token calculation and parent linkage."""
        # L1 nodes are expanded by default; L2 and L3 default to folded
        default_expanded = True if level == HierarchyLevel.L1_BACKBONE else False
        expanded_flag = is_expanded if is_expanded is not None else default_expanded

        # Token estimate: summary for collapsed, full_content for expanded
        content_to_measure = full_content if expanded_flag else summary
        tokens = max(1, (len(content_to_measure) + 3) // 4)

        node = HierarchyNode(
            node_id=node_id,
            title=title,
            level=level,
            summary=summary,
            full_content=full_content,
            parent_id=parent_id,
            children_ids=(),
            is_expanded=expanded_flag,
            is_completed=is_completed,
            token_estimate=tokens,
        )
        self._nodes[node_id] = node

        if parent_id is None:
            if node_id not in self._root_ids:
                self._root_ids.append(node_id)

        return self

    def build(self) -> HierarchyTree:
        """Resolves bidirectional child links, verifies references, and returns immutable HierarchyTree."""
        parent_to_children: dict[str, list[str]] = {nid: [] for nid in self._nodes}

        for nid, node in self._nodes.items():
            if node.parent_id is not None:
                if node.parent_id not in self._nodes:
                    raise ValueError(
                        f"Parent node '{node.parent_id}' referenced by '{nid}' not found in builder."
                    )
                parent_to_children[node.parent_id].append(nid)

        # Reconstruct nodes with resolved children_ids
        final_nodes: dict[str, HierarchyNode] = {}
        for nid, node in self._nodes.items():
            children = tuple(parent_to_children[nid])
            final_nodes[nid] = HierarchyNode(
                node_id=node.node_id,
                title=node.title,
                level=node.level,
                summary=node.summary,
                full_content=node.full_content,
                parent_id=node.parent_id,
                children_ids=children,
                is_expanded=node.is_expanded,
                is_completed=node.is_completed,
                token_estimate=node.token_estimate,
            )

        return HierarchyTree(
            root_node_ids=tuple(self._root_ids),
            nodes=final_nodes,
        )

    @classmethod
    def from_flat_specs(
        cls, specs: Sequence[dict[str, str | HierarchyLevel | bool | None]]
    ) -> HierarchyTree:
        """Convenience factory parsing a list of node specification dictionaries."""
        builder = cls()
        for s in specs:
            builder.add_node(
                node_id=str(s["node_id"]),
                title=str(s["title"]),
                level=HierarchyLevel(s["level"]),
                summary=str(s.get("summary", "")),
                full_content=str(s.get("full_content", "")),
                parent_id=str(s["parent_id"]) if s.get("parent_id") else None,
                is_expanded=bool(s["is_expanded"]) if "is_expanded" in s else None,
                is_completed=bool(s.get("is_completed", False)),
            )
        return builder.build()
