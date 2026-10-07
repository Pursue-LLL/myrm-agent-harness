"""[POS]: src/myrm_agent_harness/toolkits/memory/temporal_graph/conflict_reconciler.py
[INPUT]: SqliteTemporalGraphStore, TemporalFactEdge, and predicate exclusivity definitions.
[OUTPUT]: TemporalFactConflictReconciler detecting conflicting facts, superseding legacy edges, and tracking evolutionary lineage.
"""

from __future__ import annotations

from .models import FactConflictResolutionResult, TemporalFactEdge
from .sqlite_store import SqliteTemporalGraphStore

DEFAULT_MUTUALLY_EXCLUSIVE_PREDICATES: frozenset[str] = frozenset({
    "works_at",
    "employed_by",
    "current_framework",
    "primary_framework",
    "primary_database",
    "operating_system",
    "ide_preference",
    "role_title",
    "residence_city",
    "main_programming_language",
})


class TemporalFactConflictReconciler:
    """Detects and resolves fact contradictions by marking superseded edges in temporal memory."""

    def __init__(self, exclusive_predicates: set[str] | frozenset[str] | None = None) -> None:
        if exclusive_predicates is None:
            self._exclusive_predicates = set(DEFAULT_MUTUALLY_EXCLUSIVE_PREDICATES)
        else:
            self._exclusive_predicates = set(exclusive_predicates)

    def register_exclusive_predicate(self, predicate: str) -> None:
        """Registers an additional predicate as mutually exclusive."""
        self._exclusive_predicates.add(predicate.strip().lower())

    def is_exclusive(self, predicate: str) -> bool:
        """Checks if a predicate is registered as mutually exclusive."""
        return predicate.strip().lower() in self._exclusive_predicates

    def resolve_and_insert(
        self,
        store: SqliteTemporalGraphStore,
        new_edge: TemporalFactEdge,
    ) -> FactConflictResolutionResult:
        """Inserts a new fact edge, atomically reconciling and superseding conflicting active edges."""
        predicate_norm = new_edge.predicate.strip().lower()
        if not self.is_exclusive(predicate_norm):
            saved = store.save_edge(new_edge)
            return FactConflictResolutionResult(
                new_edge=saved,
                superseded_edges=[],
                is_conflict_detected=False,
                conflict_reason="Predicate allows multiple coexisting facts.",
            )

        # Look up existing active edges for the same source and predicate
        active_edges = store.get_edges_by_source_predicate(
            source_id=new_edge.source_id,
            predicate=new_edge.predicate,
            active_only=True,
        )

        superseded: list[TemporalFactEdge] = []
        for old_edge in active_edges:
            # If target is identical, it's a re-assertion or update
            if old_edge.target_id == new_edge.target_id and old_edge.edge_id != new_edge.edge_id:
                old_edge.is_superseded = True
                old_edge.valid_until = new_edge.valid_from
                old_edge.superseded_by = new_edge.edge_id
                store.save_edge(old_edge)
                superseded.append(old_edge)
            elif old_edge.target_id != new_edge.target_id:
                # Mutually exclusive conflict detected
                old_edge.is_superseded = True
                old_edge.valid_until = new_edge.valid_from
                old_edge.superseded_by = new_edge.edge_id
                store.save_edge(old_edge)
                superseded.append(old_edge)

        saved_new = store.save_edge(new_edge)
        has_conflict = len(superseded) > 0
        reason = (
            f"Mutually exclusive predicate '{new_edge.predicate}' superseded {len(superseded)} historical edges."
            if has_conflict
            else "No conflicting active edges found."
        )

        return FactConflictResolutionResult(
            new_edge=saved_new,
            superseded_edges=superseded,
            is_conflict_detected=has_conflict,
            conflict_reason=reason,
        )

    def get_supersession_lineage(
        self,
        store: SqliteTemporalGraphStore,
        edge_id: str,
    ) -> list[TemporalFactEdge]:
        """Traces the backward lineage of superseded edges leading up to the given edge."""
        lineage: list[TemporalFactEdge] = []
        current = store.get_edge(edge_id)
        if current is None:
            return lineage

        lineage.append(current)
        # Find preceding edges where superseded_by == current.edge_id
        while True:
            # Query edges where superseded_by is the head of the chain
            head_edge = lineage[-1]
            all_source_edges = store.get_edges_by_source_predicate(
                source_id=head_edge.source_id,
                predicate=head_edge.predicate,
                active_only=False,
            )
            predecessor = next(
                (e for e in all_source_edges if e.superseded_by == head_edge.edge_id and e.edge_id not in {x.edge_id for x in lineage}),
                None,
            )
            if predecessor is None:
                break
            lineage.append(predecessor)

        return lineage
