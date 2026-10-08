"""Causality derivation graph engine with topological cycle detection and traversal."""

from __future__ import annotations

import threading
from collections import deque

from myrm_agent_harness.toolkits.memory.conclusion_evidence.models import (
    AttributedConclusion,
    AttributionLevel,
    ConclusionEvidenceStats,
    DerivationCycleError,
    DerivationTraversalView,
)


class ConclusionDerivationGraphEngine:
    """Maintains a directed acyclic graph (DAG) of premise-to-derivative conclusions."""

    def __init__(self) -> None:
        self._conclusions: dict[str, AttributedConclusion] = {}
        # premise_id -> set of derivative_ids
        self._downstream_edges: dict[str, set[str]] = {}
        # derivative_id -> set of premise_ids
        self._upstream_edges: dict[str, set[str]] = {}
        self._lock: threading.Lock = threading.Lock()

    def add_conclusion(self, conclusion: AttributedConclusion) -> AttributedConclusion:
        """Inserts an attributed conclusion into the DAG, preventing cyclic derivations.

        If a conclusion with the same ID already exists, increments times_derived.
        """
        with self._lock:
            # Check for existing node to increment derivation count
            if conclusion.conclusion_id in self._conclusions:
                existing: AttributedConclusion = self._conclusions[conclusion.conclusion_id]
                updated = AttributedConclusion(
                    conclusion_id=existing.conclusion_id,
                    peer_id=existing.peer_id,
                    content=existing.content,
                    level=existing.level,
                    source_ids=existing.source_ids,
                    times_derived=existing.times_derived + 1,
                    evidence_message_ids=existing.evidence_message_ids,
                    scope_tag=existing.scope_tag,
                    status=existing.status,
                    created_at=existing.created_at,
                    metadata=dict(existing.metadata),
                )
                self._conclusions[conclusion.conclusion_id] = updated
                return updated

            # Validate that adding this conclusion does not introduce a cycle
            self._verify_no_cycle(conclusion.conclusion_id, conclusion.source_ids)

            # Store node
            self._conclusions[conclusion.conclusion_id] = conclusion
            if conclusion.conclusion_id not in self._upstream_edges:
                self._upstream_edges[conclusion.conclusion_id] = set()
            if conclusion.conclusion_id not in self._downstream_edges:
                self._downstream_edges[conclusion.conclusion_id] = set()

            # Record edges
            for premise_id in conclusion.source_ids:
                if premise_id not in self._downstream_edges:
                    self._downstream_edges[premise_id] = set()
                self._downstream_edges[premise_id].add(conclusion.conclusion_id)
                self._upstream_edges[conclusion.conclusion_id].add(premise_id)

            return conclusion

    def _verify_no_cycle(self, candidate_id: str, proposed_premise_ids: tuple[str, ...]) -> None:
        """Ensures proposed premises cannot reach candidate_id via existing upstream paths."""
        if candidate_id in proposed_premise_ids:
            raise DerivationCycleError(f"Self-referential derivation cycle detected for conclusion '{candidate_id}'.")

        visited: set[str] = set()
        queue: deque[str] = deque(proposed_premise_ids)

        while queue:
            current: str = queue.popleft()
            if current == candidate_id:
                raise DerivationCycleError(
                    f"Cyclic derivation detected: premise '{current}' leads back to '{candidate_id}'."
                )
            if current in visited:
                continue
            visited.add(current)
            for upstream in self._upstream_edges.get(current, set()):
                if upstream not in visited:
                    queue.append(upstream)

    def get_conclusion(self, conclusion_id: str) -> AttributedConclusion | None:
        """Retrieves a single conclusion node by ID."""
        with self._lock:
            return self._conclusions.get(conclusion_id)

    def get_premise_conclusions(self, conclusion_id: str, max_depth: int = 5) -> tuple[AttributedConclusion, ...]:
        """Traverses upstream to collect all supporting premise conclusions."""
        with self._lock:
            if conclusion_id not in self._conclusions:
                return ()

            results: list[AttributedConclusion] = []
            visited: set[str] = {conclusion_id}
            queue: deque[tuple[str, int]] = deque([(conclusion_id, 0)])

            while queue:
                curr_id, depth = queue.popleft()
                if depth >= max_depth:
                    continue

                for premise_id in self._upstream_edges.get(curr_id, set()):
                    if premise_id not in visited:
                        visited.add(premise_id)
                        if premise_id in self._conclusions:
                            results.append(self._conclusions[premise_id])
                        queue.append((premise_id, depth + 1))

            return tuple(results)

    def get_derived_conclusions(self, conclusion_id: str, max_depth: int = 5) -> tuple[AttributedConclusion, ...]:
        """Traverses downstream to collect all conclusions derived from this conclusion."""
        with self._lock:
            if conclusion_id not in self._conclusions:
                return ()

            results: list[AttributedConclusion] = []
            visited: set[str] = {conclusion_id}
            queue: deque[tuple[str, int]] = deque([(conclusion_id, 0)])

            while queue:
                curr_id, depth = queue.popleft()
                if depth >= max_depth:
                    continue

                for child_id in self._downstream_edges.get(curr_id, set()):
                    if child_id not in visited:
                        visited.add(child_id)
                        if child_id in self._conclusions:
                            results.append(self._conclusions[child_id])
                        queue.append((child_id, depth + 1))

            return tuple(results)

    def traverse_two_way(self, conclusion_id: str, max_depth: int = 5) -> DerivationTraversalView:
        """Performs two-way causal traversal rooted at the given conclusion ID."""
        premises = self.get_premise_conclusions(conclusion_id, max_depth=max_depth)
        derivatives = self.get_derived_conclusions(conclusion_id, max_depth=max_depth)
        return DerivationTraversalView(
            conclusion_id=conclusion_id,
            upstream_premises=premises,
            downstream_derivatives=derivatives,
            max_depth=max_depth,
        )

    def analyze_invalidation_cascade(self, conclusion_id: str) -> tuple[str, ...]:
        """Computes topological list of all downstream conclusion IDs invalidated if node is removed."""
        derivatives = self.get_derived_conclusions(conclusion_id, max_depth=20)
        return tuple(c.conclusion_id for c in derivatives)

    def remove_conclusion(self, conclusion_id: str) -> bool:
        """Removes a conclusion and prunes its incident edges from the DAG."""
        with self._lock:
            if conclusion_id not in self._conclusions:
                return False

            self._conclusions.pop(conclusion_id, None)

            # Prune outgoing downstream edges
            if conclusion_id in self._downstream_edges:
                children = self._downstream_edges.pop(conclusion_id)
                for child_id in children:
                    if child_id in self._upstream_edges:
                        self._upstream_edges[child_id].discard(conclusion_id)

            # Prune incoming upstream edges
            if conclusion_id in self._upstream_edges:
                parents = self._upstream_edges.pop(conclusion_id)
                for parent_id in parents:
                    if parent_id in self._downstream_edges:
                        self._downstream_edges[parent_id].discard(conclusion_id)

            return True

    def get_all_conclusions(self) -> list[AttributedConclusion]:
        """Returns snapshot list of all registered conclusions."""
        with self._lock:
            return list(self._conclusions.values())

    def get_stats(self) -> ConclusionEvidenceStats:
        """Computes DAG edge counts and derivation depth statistics."""
        with self._lock:
            total_nodes = len(self._conclusions)
            total_explicit = sum(1 for c in self._conclusions.values() if c.level == AttributionLevel.EXPLICIT)
            total_derived = total_nodes - total_explicit
            total_edges = sum(len(sub) for sub in self._downstream_edges.values())

            # Compute maximum derivation depth via BFS from roots
            max_depth = 0
            roots = [cid for cid in self._conclusions if not self._upstream_edges.get(cid, set())]
            for root_id in roots:
                q: deque[tuple[str, int]] = deque([(root_id, 1)])
                while q:
                    curr, d = q.popleft()
                    if d > max_depth:
                        max_depth = d
                    for nxt in self._downstream_edges.get(curr, set()):
                        q.append((nxt, d + 1))

            return ConclusionEvidenceStats(
                total_conclusions=total_nodes,
                total_explicit=total_explicit,
                total_derived=total_derived,
                total_edges=total_edges,
                max_derivation_depth=max_depth,
            )
