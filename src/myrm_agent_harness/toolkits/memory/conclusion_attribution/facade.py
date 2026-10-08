"""Unified facade for Conclusion Attribution and Chat Evidence Suite.

Coordinates bidirectional graph traversal, evidence gathering,
ripple impact simulation, and attribution lifecycle.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.conclusion_attribution.attribution_graph import (
    AttributionGraphEngine,
)
from myrm_agent_harness.toolkits.memory.conclusion_attribution.evidence_collector import (
    EvidenceCollector,
)
from myrm_agent_harness.toolkits.memory.conclusion_attribution.models import (
    AttributedConclusion,
    AttributionLevel,
    AttributionMetrics,
    ChatEvidence,
    GraphTraversalNode,
    RippleImpactReport,
)


class ConclusionAttributionSuite:
    """Unified coordinator facade for causal memory attribution."""

    def __init__(self) -> None:
        self._store: dict[str, AttributedConclusion] = {}
        self._graph_engine = AttributionGraphEngine()

    def create_conclusion(
        self,
        peer_id: str,
        content: str,
        level: AttributionLevel = AttributionLevel.EXPLICIT,
        source_ids: list[str] | None = None,
        session_id: str | None = None,
        confidence: float = 1.0,
        metadata: dict[str, str] | None = None,
    ) -> AttributedConclusion:
        """Create and register an attributed memory conclusion with cycle checking."""
        src_ids = list(source_ids or [])
        now_iso = datetime.now(UTC).isoformat()
        conclusion_id = f"conc_{uuid.uuid4().hex[:12]}"

        # Cycle check if prospective premises are specified
        if src_ids and self._graph_engine.detect_cycles(conclusion_id, src_ids, self._store):
            raise ValueError(
                f"Cyclic dependency detected: linking {conclusion_id} to {src_ids} would create a circular premise chain."
            )

        # Check existing source validity
        for s_id in src_ids:
            if s_id in self._store:
                # Increment premise observation confidence
                self._store[s_id].times_derived += 1

        conclusion = AttributedConclusion(
            id=conclusion_id,
            peer_id=peer_id,
            content=content.strip(),
            level=level,
            source_ids=src_ids,
            times_derived=1,
            session_id=session_id,
            confidence=max(0.0, min(1.0, confidence)),
            created_at=now_iso,
            updated_at=now_iso,
            metadata=dict(metadata or {}),
        )
        self._store[conclusion_id] = conclusion
        return conclusion

    def get_conclusion(self, conclusion_id: str) -> AttributedConclusion | None:
        """Retrieve a single conclusion by ID."""
        return self._store.get(conclusion_id)

    def get_conclusions_by_ids(self, conclusion_ids: list[str]) -> list[AttributedConclusion]:
        """Fetch multiple conclusions in specified order."""
        return [self._store[c_id] for c_id in conclusion_ids if c_id in self._store]

    def list_conclusions(
        self,
        peer_id: str | None = None,
        session_id: str | None = None,
        level: AttributionLevel | None = None,
        reverse: bool = False,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[AttributedConclusion], int]:
        """List conclusions with pagination and multi-attribute filters."""
        matched: list[AttributedConclusion] = list(self._store.values())

        if peer_id is not None:
            matched = [c for c in matched if c.peer_id == peer_id]
        if session_id is not None:
            matched = [c for c in matched if c.session_id == session_id]
        if level is not None:
            matched = [c for c in matched if c.level == level]

        matched.sort(key=lambda x: x.created_at, reverse=not reverse)
        total = len(matched)
        start = (page - 1) * size
        end = start + size
        return matched[start:end], total

    def query_conclusions(
        self,
        query: str,
        peer_id: str | None = None,
        level: AttributionLevel | None = None,
        top_k: int = 10,
    ) -> list[AttributedConclusion]:
        """Semantic/keyword search across conclusions with confidence-weighted ranking."""
        tokens = [t.lower() for t in query.strip().split() if t.strip()]
        matched: list[tuple[float, AttributedConclusion]] = []

        for c in self._store.values():
            if peer_id and c.peer_id != peer_id:
                continue
            if level and c.level != level:
                continue

            content_lower = c.content.lower()
            hit_score = 0.0
            for tok in tokens:
                if tok in content_lower:
                    hit_score += 1.0

            if hit_score > 0.0 or not tokens:
                # Composite score: hit frequency + confidence + logarithmic times_derived bonus
                composite = (
                    hit_score * 2.0
                    + c.confidence * 1.5
                    + min(3.0, (c.times_derived - 1) * 0.5)
                )
                matched.append((composite, c))

        matched.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in matched[:top_k]]

    def walk_downward(self, conclusion_id: str, max_depth: int = 15) -> list[GraphTraversalNode]:
        """Walk downwards towards explicit root facts."""
        return self._graph_engine.walk_downward_premises(conclusion_id, self._store, max_depth)

    def walk_upward(self, premise_id: str, max_depth: int = 15) -> list[GraphTraversalNode]:
        """Walk upwards towards derived conclusions."""
        return self._graph_engine.walk_upward_derivations(premise_id, self._store, max_depth)

    def get_ripple_impact(self, conclusion_id: str) -> RippleImpactReport:
        """Calculate ripple impact report for a candidate conclusion deletion or edit."""
        return self._graph_engine.calculate_ripple_impact(conclusion_id, self._store)

    def delete_conclusion(self, conclusion_id: str, cascade: bool = False) -> list[str]:
        """Delete a conclusion. If cascade=True, deletes all derived conclusions recursively."""
        if conclusion_id not in self._store:
            return []

        deleted_ids: list[str] = []
        if cascade:
            upward_nodes = self.walk_upward(conclusion_id)
            # Delete in reverse topological order (deepest derived first)
            for node in reversed(upward_nodes):
                c_id = node.conclusion.id
                if c_id in self._store:
                    del self._store[c_id]
                    deleted_ids.append(c_id)
        else:
            del self._store[conclusion_id]
            deleted_ids.append(conclusion_id)
            # Remove from downstream source_ids to prevent dangling pointers
            for item in self._store.values():
                if conclusion_id in item.source_ids:
                    item.source_ids.remove(conclusion_id)

        return deleted_ids

    def reinforce_conclusion(self, conclusion_id: str) -> AttributedConclusion:
        """Reinforce verification of a conclusion, bumping times_derived and confidence."""
        item = self._store.get(conclusion_id)
        if not item:
            raise KeyError(f"Conclusion not found: {conclusion_id}")
        item.times_derived += 1
        item.confidence = min(1.0, item.confidence + 0.05)
        item.updated_at = datetime.now(UTC).isoformat()
        return item

    def create_evidence_package(
        self,
        query: str,
        peer_id: str,
        session_id: str | None = None,
        top_k: int = 3,
    ) -> ChatEvidence:
        """Build a verifiable ChatEvidence package for transparent contextual audit."""
        collector = EvidenceCollector(session_id=session_id)
        matched = self.query_conclusions(query, peer_id=peer_id, top_k=top_k)
        collector.record_conclusions(matched)

        # Record mock grounding message reference if session provided
        if session_id:
            collector.record_message_reference(
                message_id=f"msg_{session_id[:8]}",
                session_id=session_id,
                snippet=f"User query grounding: '{query}'",
                role="user",
            )
        collector.record_tool_call(
            tool_name="query_conclusions",
            tool_input={"query": query, "peer_id": peer_id},
            tool_output_snippet=f"Retrieved {len(matched)} attributed conclusions",
        )
        return collector.assemble()

    def get_metrics(self, peer_id: str | None = None) -> AttributionMetrics:
        """Compute aggregate metrics over all conclusions."""
        items = list(self._store.values())
        if peer_id:
            items = [c for c in items if c.peer_id == peer_id]

        if not items:
            return AttributionMetrics()

        explicit_c = sum(1 for c in items if c.level == AttributionLevel.EXPLICIT)
        deductive_c = sum(1 for c in items if c.level == AttributionLevel.DEDUCTIVE)
        inductive_c = sum(1 for c in items if c.level == AttributionLevel.INDUCTIVE)
        contradiction_c = sum(1 for c in items if c.level == AttributionLevel.CONTRADICTION)
        avg_derived = sum(c.times_derived for c in items) / len(items)

        # Calculate max depth
        max_d = 0
        for it in items:
            depth = len(self._graph_engine.walk_downward_premises(it.id, self._store)) - 1
            if depth > max_d:
                max_d = depth

        return AttributionMetrics(
            total_conclusions=len(items),
            explicit_count=explicit_c,
            deductive_count=deductive_c,
            inductive_count=inductive_c,
            contradiction_count=contradiction_c,
            max_derivation_depth=max(0, max_d),
            average_times_derived=round(avg_derived, 2),
        )
