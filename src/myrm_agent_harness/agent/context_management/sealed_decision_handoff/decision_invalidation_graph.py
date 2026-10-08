# [INPUT] DecisionNode, NegativeInvariant, HandoffSanityReport
# [OUTPUT] DecisionInvalidationGraph
# [POS] Decision revision, invalidation graph, topology sanity checker, and negative invariant extractor

"""Decision invalidation graph and lineage reconciliation for sealed handoffs."""

from __future__ import annotations

from dataclasses import replace

from myrm_agent_harness.agent.context_management.sealed_decision_handoff.sealed_decision_types import (
    DecisionDict,
    DecisionGraphCycleError,
    DecisionNode,
    DecisionStatus,
    HandoffSanityReport,
    NegativeInvariant,
)


class DecisionInvalidationGraph:
    """Manages directed revision lineage, active resolution, and negative invariants."""

    def __init__(self) -> None:
        self._nodes: dict[str, DecisionNode] = {}

    def add_decision(self, node: DecisionNode) -> DecisionNode:
        """Register a new decision node into the graph."""
        if node.supersedes_id and node.supersedes_id == node.node_id:
            raise DecisionGraphCycleError(
                f"Decision {node.node_id} cannot supersede itself"
            )
        self._nodes[node.node_id] = node
        return node

    def revoke_decision(self, node_id: str, reason: str) -> DecisionNode:
        """Explicitly revoke a decision, marking it invalid and non-inheritable."""
        if node_id not in self._nodes:
            raise KeyError(f"Decision node '{node_id}' does not exist in graph")

        target = self._nodes[node_id]
        revoked_node = replace(
            target,
            status="REVOKED",
            revoked_reason=reason,
        )
        self._nodes[node_id] = revoked_node
        return revoked_node

    def supersede_decision(
        self,
        old_node_id: str,
        new_node: DecisionNode,
    ) -> DecisionNode:
        """Supersede an older decision with a refined decision."""
        if old_node_id not in self._nodes:
            raise KeyError(f"Target decision '{old_node_id}' to supersede not found")

        old_target = self._nodes[old_node_id]
        superseded_old = replace(
            old_target,
            status="SUPERSEDED",
            revoked_reason=f"Superseded by {new_node.node_id}: {new_node.title}",
        )
        self._nodes[old_node_id] = superseded_old

        linked_new = replace(new_node, supersedes_id=old_node_id, status="ACTIVE")
        self._nodes[new_node.node_id] = linked_new
        self._detect_cycles()
        return linked_new

    def get_decision(self, node_id: str) -> DecisionNode | None:
        """Retrieve a specific decision node by identifier."""
        return self._nodes.get(node_id)

    def list_all_decisions(self) -> list[DecisionNode]:
        """Return all registered decision nodes in registration order."""
        return list(self._nodes.values())

    def get_active_decisions(self) -> list[DecisionNode]:
        """Return only active decisions topologically ordered by lineage."""
        self._detect_cycles()
        return [node for node in self._nodes.values() if node.status == "ACTIVE"]

    def extract_negative_invariants(self) -> list[NegativeInvariant]:
        """Extract explicit negative invariants from revoked and superseded decisions."""
        invariants: list[NegativeInvariant] = []

        for node in self._nodes.values():
            if node.status == "REVOKED":
                invariants.append(
                    NegativeInvariant(
                        rule=f"DO NOT ADOPT: {node.chosen_option} ({node.title})",
                        context=f"Intent: {node.intent}. Rationale previously was: {node.rationale}",
                        source_decision_id=node.node_id,
                        revocation_reason=node.revoked_reason or "Explicitly revoked by user or agent",
                    )
                )
            elif node.status == "SUPERSEDED":
                invariants.append(
                    NegativeInvariant(
                        rule=f"DEPRECATED CHOICE: {node.chosen_option} ({node.title})",
                        context=f"Superseded by successor decision. Intent: {node.intent}",
                        source_decision_id=node.node_id,
                        revocation_reason=node.revoked_reason or "Superseded by newer revision",
                    )
                )

            # Also add explicitly rejected alternatives as negative invariants
            for rejected in node.rejected_options:
                invariants.append(
                    NegativeInvariant(
                        rule=f"REJECTED ALTERNATIVE: {rejected}",
                        context=f"Considered and rejected during decision '{node.title}' ({node.node_id})",
                        source_decision_id=node.node_id,
                        revocation_reason=f"Selected '{node.chosen_option}' instead because: {node.rationale}",
                    )
                )

        return invariants

    def verify_handoff_sanity(self) -> HandoffSanityReport:
        """Conduct handoff sanity verification against the decision graph."""
        warnings: list[str] = []
        active_count = 0
        revoked_count = 0
        superseded_count = 0

        for node in self._nodes.values():
            if node.status == "ACTIVE":
                active_count += 1
            elif node.status == "REVOKED":
                revoked_count += 1
            elif node.status == "SUPERSEDED":
                superseded_count += 1

            if node.supersedes_id and node.supersedes_id not in self._nodes:
                warnings.append(
                    f"Decision {node.node_id} supersedes missing node '{node.supersedes_id}'"
                )

        try:
            self._detect_cycles()
        except DecisionGraphCycleError as err:
            warnings.append(str(err))

        negative_invariants = self.extract_negative_invariants()
        is_valid = len(warnings) == 0

        return HandoffSanityReport(
            is_valid=is_valid,
            active_count=active_count,
            revoked_count=revoked_count,
            superseded_count=superseded_count,
            negative_invariants_count=len(negative_invariants),
            conflict_warnings=warnings,
        )

    def _detect_cycles(self) -> None:
        """Detect invalidation cycles along supersedes pointer chains."""
        for start_id, node in self._nodes.items():
            visited: set[str] = {start_id}
            current_id = node.supersedes_id

            while current_id:
                if current_id in visited:
                    raise DecisionGraphCycleError(
                        f"Cycle detected in supersedes lineage involving node '{current_id}'"
                    )
                visited.add(current_id)
                next_node = self._nodes.get(current_id)
                current_id = next_node.supersedes_id if next_node else None

    def to_dict(self) -> dict[str, list[DecisionDict]]:
        """Serialize graph to dictionary."""
        return {
            "nodes": [node.to_dict() for node in self._nodes.values()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, list[DecisionDict]]) -> DecisionInvalidationGraph:
        """Hydrate graph from dictionary."""
        graph = cls()
        for node_dict in data.get("nodes", []):
            graph.add_decision(DecisionNode.from_dict(node_dict))
        return graph
