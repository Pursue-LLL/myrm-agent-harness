"""Graph traversal engine for conclusion attribution and causal reasoning trees.

Provides bidirectional premise-derivation tree traversal, cycle detection,
and ripple impact simulation for robust memory governance.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import Literal

from myrm_agent_harness.toolkits.memory.conclusion_attribution.models import (
    AttributedConclusion,
    GraphTraversalNode,
    RippleImpactReport,
)


class AttributionGraphEngine:
    """Engine handling bidirectional reasoning graph traversals and impact calculations."""

    @staticmethod
    def detect_cycles(
        target_id: str,
        prospective_source_ids: list[str],
        store: Mapping[str, AttributedConclusion],
    ) -> bool:
        """Detect whether linking target_id to prospective_source_ids creates a cycle.

        Returns True if a cycle would be created, False otherwise.
        """
        visited: set[str] = set()
        queue: deque[str] = deque(prospective_source_ids)

        while queue:
            current_id = queue.popleft()
            if current_id == target_id:
                return True
            if current_id in visited:
                continue
            visited.add(current_id)

            node = store.get(current_id)
            if node:
                for src_id in node.source_ids:
                    if src_id not in visited:
                        queue.append(src_id)
        return False

    @staticmethod
    def walk_downward_premises(
        conclusion_id: str,
        store: Mapping[str, AttributedConclusion],
        max_depth: int = 15,
    ) -> list[GraphTraversalNode]:
        """Walk downwards along premise edges (conclusion -> sources).

        Returns a topological ordered list of ancestor nodes down to explicit roots.
        """
        root = store.get(conclusion_id)
        if not root:
            return []

        results: list[GraphTraversalNode] = []
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(conclusion_id, 0)])

        while queue:
            curr_id, depth = queue.popleft()
            if curr_id in visited or depth > max_depth:
                continue
            visited.add(curr_id)

            curr_obj = store.get(curr_id)
            if not curr_obj:
                continue

            # Direct children in downward traversal are its sources
            results.append(
                GraphTraversalNode(
                    conclusion=curr_obj,
                    depth=depth,
                    direct_parent_ids=[],
                    direct_child_ids=list(curr_obj.source_ids),
                )
            )

            for parent_src_id in curr_obj.source_ids:
                if parent_src_id not in visited and parent_src_id in store:
                    queue.append((parent_src_id, depth + 1))

        return results

    @staticmethod
    def walk_upward_derivations(
        premise_id: str,
        store: Mapping[str, AttributedConclusion],
        max_depth: int = 15,
    ) -> list[GraphTraversalNode]:
        """Walk upwards along derivation edges (premise -> derived conclusions).

        Returns nodes that were derived from or depended upon premise_id.
        """
        if premise_id not in store:
            return []

        # Build reverse index: premise_id -> list of derived conclusion ids
        reverse_index: dict[str, list[str]] = {}
        for c_id, c_val in store.items():
            for src_id in c_val.source_ids:
                reverse_index.setdefault(src_id, []).append(c_id)

        results: list[GraphTraversalNode] = []
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(premise_id, 0)])

        while queue:
            curr_id, depth = queue.popleft()
            if curr_id in visited or depth > max_depth:
                continue
            visited.add(curr_id)

            curr_obj = store.get(curr_id)
            if not curr_obj:
                continue

            derived_children = reverse_index.get(curr_id, [])
            results.append(
                GraphTraversalNode(
                    conclusion=curr_obj,
                    depth=depth,
                    direct_parent_ids=list(curr_obj.source_ids),
                    direct_child_ids=derived_children,
                )
            )

            for child_id in derived_children:
                if child_id not in visited and child_id in store:
                    queue.append((child_id, depth + 1))

        return results

    @classmethod
    def calculate_ripple_impact(
        cls,
        conclusion_id: str,
        store: Mapping[str, AttributedConclusion],
    ) -> RippleImpactReport:
        """Simulate and assess the downstream impact if conclusion_id is retracted or invalidated."""
        upward_nodes = cls.walk_upward_derivations(conclusion_id, store)
        # Exclude the target node itself
        impacted_nodes = [n for n in upward_nodes if n.conclusion.id != conclusion_id]
        impacted_ids = [n.conclusion.id for n in impacted_nodes]
        max_depth = max([n.depth for n in impacted_nodes], default=0)

        count = len(impacted_ids)
        severity: Literal["low", "medium", "high", "critical"]
        if count == 0:
            severity = "low"
            explanation = "No downstream conclusions rely on this premise. Safe to modify or delete."
        elif count <= 2:
            severity = "medium"
            explanation = f"Affects {count} derived conclusions. Low ripple blast radius."
        elif count <= 6:
            severity = "high"
            explanation = f"Affects {count} derived conclusions across depth {max_depth}. Requires re-evaluation."
        else:
            severity = "critical"
            explanation = f"Foundational premise affecting {count} downstream conclusions! High structural risk."

        return RippleImpactReport(
            target_conclusion_id=conclusion_id,
            impacted_conclusion_ids=impacted_ids,
            depth_reached=max_depth,
            severity=severity,
            explanation=explanation,
        )
