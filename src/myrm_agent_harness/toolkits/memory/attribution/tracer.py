"""Memory Lifecycle Tracer documenting single-trace attribution flows.

[INPUT]
- toolkits.memory.attribution.models::AttributionGraphEdge, AttributionGraphNode, AttributionGraphPayload,
  CandidateRecallItem, DiscardedRecallItem, InjectedContextItem, MemoryAttributionTrace, ModelCitationItem
  (POS: Data models for Full-Lifecycle Memory Attribution and Explainable Traceability Matrix.)

[OUTPUT]
- MemoryLifecycleTracer: Tracks and records full-lifecycle memory flows from initial query to final
  citation.

[POS]
Memory Lifecycle Tracer documenting single-trace attribution flows.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from .models import (
    AttributionGraphEdge,
    AttributionGraphNode,
    AttributionGraphPayload,
    CandidateRecallItem,
    DiscardedRecallItem,
    InjectedContextItem,
    MemoryAttributionTrace,
    ModelCitationItem,
)


class MemoryLifecycleTracer:
    """Tracks and records full-lifecycle memory flows from initial query to final citation."""

    def __init__(self) -> None:
        """Initialize in-memory trace registry and revocation ledger."""
        self._traces: dict[str, MemoryAttributionTrace] = {}
        self._revocations: dict[str, str] = {}  # memory_id -> revocation_reason

    @property
    def total_traces(self) -> int:
        """Return total count of recorded traces."""
        return len(self._traces)

    def start_trace(self, session_id: str, query_text: str) -> str:
        """Begin an end-to-end memory attribution trace.

        Args:
            session_id: Target session identifier.
            query_text: Initiating query string.

        Returns:
            Generated unique trace ID.
        """
        trace_id = f"trace-{uuid.uuid4().hex[:12]}"
        trace = MemoryAttributionTrace(
            trace_id=trace_id,
            session_id=session_id,
            query_text=query_text,
            created_at=datetime.now(UTC),
        )
        self._traces[trace_id] = trace
        return trace_id

    def record_candidates(
        self,
        trace_id: str,
        candidates: Sequence[CandidateRecallItem],
    ) -> None:
        """Record candidates retrieved during the recall stage."""
        trace = self._get_active_trace(trace_id)
        trace.candidate_recalls.extend(candidates)

    def record_discarded(
        self,
        trace_id: str,
        discarded: Sequence[DiscardedRecallItem],
    ) -> None:
        """Record items pruned or discarded with explicit causes."""
        trace = self._get_active_trace(trace_id)
        trace.discarded_items.extend(discarded)

    def record_injections(
        self,
        trace_id: str,
        injections: Sequence[InjectedContextItem],
    ) -> None:
        """Record memories formatted and injected into prompt context."""
        trace = self._get_active_trace(trace_id)
        trace.prompt_injections.extend(injections)

    def record_citations(
        self,
        trace_id: str,
        citations: Sequence[ModelCitationItem],
    ) -> None:
        """Record memories cited by the model in generated output."""
        trace = self._get_active_trace(trace_id)
        trace.model_citations.extend(citations)

    def finalize_trace(
        self,
        trace_id: str,
        duration_ms: float = 0.0,
    ) -> MemoryAttributionTrace:
        """Mark trace as finalized with measured elapsed latency."""
        trace = self._get_active_trace(trace_id)
        trace.duration_ms = max(0.0, duration_ms)
        trace.is_finalized = True
        return trace

    def get_trace(self, trace_id: str) -> MemoryAttributionTrace | None:
        """Retrieve trace by ID."""
        return self._traces.get(trace_id)

    def list_traces(self, session_id: str | None = None) -> list[MemoryAttributionTrace]:
        """List recorded traces, optionally filtered by session."""
        if session_id is None:
            return list(self._traces.values())
        return [t for t in self._traces.values() if t.session_id == session_id]

    def export_attribution_graph(self, trace_id: str) -> AttributionGraphPayload:
        """Project the single-trace lifecycle into a graph of nodes and edges for visualization.

        Args:
            trace_id: Identifier of trace to project.

        Returns:
            AttributionGraphPayload containing nodes and edges.

        Raises:
            KeyError: If trace_id does not exist.
        """
        trace = self._traces.get(trace_id)
        if not trace:
            raise KeyError(f"Trace '{trace_id}' not found.")

        nodes: list[AttributionGraphNode] = []
        edges: list[AttributionGraphEdge] = []

        # 1. Root Query Node
        query_node_id = f"node-query-{trace.trace_id}"
        nodes.append(
            AttributionGraphNode(
                node_id=query_node_id,
                node_type="query",
                label="User Query",
                details=trace.query_text,
            )
        )

        # 2. Candidate Nodes
        for cand in trace.candidate_recalls:
            cand_node_id = f"node-cand-{cand.memory_id}"
            nodes.append(
                AttributionGraphNode(
                    node_id=cand_node_id,
                    node_type="candidate",
                    label=f"Candidate [{cand.memory_id}]",
                    details=f"Score: {cand.score:.2f} | {cand.content_preview}",
                )
            )
            edges.append(
                AttributionGraphEdge(
                    source=query_node_id,
                    target=cand_node_id,
                    relation="recalled",
                )
            )

        # 3. Discarded Nodes
        for disc in trace.discarded_items:
            disc_node_id = f"node-disc-{disc.memory_id}"
            nodes.append(
                AttributionGraphNode(
                    node_id=disc_node_id,
                    node_type="discarded",
                    label=f"Discarded [{disc.discard_reason}]",
                    details=disc.rationale,
                )
            )
            edges.append(
                AttributionGraphEdge(
                    source=f"node-cand-{disc.memory_id}",
                    target=disc_node_id,
                    relation=f"discarded:{disc.discard_reason}",
                )
            )

        # 4. Injected Nodes
        for inj in trace.prompt_injections:
            inj_node_id = f"node-inj-{inj.memory_id}"
            nodes.append(
                AttributionGraphNode(
                    node_id=inj_node_id,
                    node_type="injected",
                    label=f"Injected [#{inj.position_index}]",
                    details=f"Tokens: {inj.token_count} | {inj.formatted_preview}",
                )
            )
            edges.append(
                AttributionGraphEdge(
                    source=f"node-cand-{inj.memory_id}",
                    target=inj_node_id,
                    relation="injected_into_prompt",
                )
            )

        # 5. Cited Nodes
        for cite in trace.model_citations:
            cite_node_id = f"node-cite-{cite.memory_id}"
            nodes.append(
                AttributionGraphNode(
                    node_id=cite_node_id,
                    node_type="cited",
                    label=f"Cited [{cite.memory_id}]",
                    details=f"Conf: {cite.confidence:.2f} | Snippet: {cite.citation_snippet}",
                )
            )
            edges.append(
                AttributionGraphEdge(
                    source=f"node-inj-{cite.memory_id}",
                    target=cite_node_id,
                    relation="cited_in_response",
                )
            )

        return AttributionGraphPayload(nodes=nodes, edges=edges)

    def mark_memory_revoked(self, memory_id: str, reason: str) -> None:
        """Record formal revocation of a tainted or obsolete memory."""
        self._revocations[memory_id] = reason

    def find_traces_citing_memory(self, memory_id: str) -> list[str]:
        """Audit trail: locate all traces whose output relied on a given memory."""
        return [
            t.trace_id
            for t in self._traces.values()
            if any(c.memory_id == memory_id for c in t.model_citations)
        ]

    def _get_active_trace(self, trace_id: str) -> MemoryAttributionTrace:
        trace = self._traces.get(trace_id)
        if not trace:
            raise KeyError(f"Trace '{trace_id}' not found.")
        return trace
