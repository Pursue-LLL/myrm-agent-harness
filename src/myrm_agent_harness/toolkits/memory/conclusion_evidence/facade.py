"""Unified facade for conclusion attribution and chat evidence verification suite."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.conclusion_evidence.derivation_graph import (
    ConclusionDerivationGraphEngine,
)
from myrm_agent_harness.toolkits.memory.conclusion_evidence.evidence_service import (
    ChatEvidenceService,
)
from myrm_agent_harness.toolkits.memory.conclusion_evidence.models import (
    AttributedConclusion,
    ChatEvidenceBundle,
    ConclusionEvidenceStats,
    DerivationTraversalView,
    MessageEvidenceItem,
    ToolCallEvidenceItem,
)


class ConclusionEvidenceSuite:
    """Unified entry point for attributed conclusions, derivation graphs, and chat evidence."""

    def __init__(self) -> None:
        self._graph: ConclusionDerivationGraphEngine = ConclusionDerivationGraphEngine()
        self._evidence: ChatEvidenceService = ChatEvidenceService(graph_engine=self._graph)

    @property
    def graph(self) -> ConclusionDerivationGraphEngine:
        """Returns the underlying derivation graph engine."""
        return self._graph

    @property
    def evidence_service(self) -> ChatEvidenceService:
        """Returns the underlying chat evidence service."""
        return self._evidence

    def add_conclusion(self, conclusion: AttributedConclusion) -> AttributedConclusion:
        """Registers an attributed conclusion, checking for causality cycles."""
        return self._graph.add_conclusion(conclusion)

    def get_conclusion(self, conclusion_id: str) -> AttributedConclusion | None:
        """Retrieves a single conclusion by ID."""
        return self._graph.get_conclusion(conclusion_id)

    def get_premise_conclusions(self, conclusion_id: str, max_depth: int = 5) -> tuple[AttributedConclusion, ...]:
        """Traverses upstream premises."""
        return self._graph.get_premise_conclusions(conclusion_id, max_depth=max_depth)

    def get_derived_conclusions(self, conclusion_id: str, max_depth: int = 5) -> tuple[AttributedConclusion, ...]:
        """Traverses downstream derivative conclusions."""
        return self._graph.get_derived_conclusions(conclusion_id, max_depth=max_depth)

    def traverse_two_way(self, conclusion_id: str, max_depth: int = 5) -> DerivationTraversalView:
        """Computes two-way causal traversal rooted at conclusion."""
        return self._graph.traverse_two_way(conclusion_id, max_depth=max_depth)

    def analyze_invalidation_cascade(self, conclusion_id: str) -> tuple[str, ...]:
        """Computes downstream conclusion IDs invalidated if premise is retracted."""
        return self._graph.analyze_invalidation_cascade(conclusion_id)

    def remove_conclusion(self, conclusion_id: str) -> bool:
        """Removes a conclusion and prunes associated edges."""
        return self._graph.remove_conclusion(conclusion_id)

    def register_message_evidence(self, item: MessageEvidenceItem) -> None:
        """Stores a snapshot message snippet for ground truth provenance."""
        self._evidence.register_message_evidence(item)

    def record_tool_call(self, tool_call: ToolCallEvidenceItem) -> None:
        """Records a tool execution trace."""
        self._evidence.record_tool_call(tool_call)

    def query_evidence_for_conclusion(self, conclusion_id: str) -> ChatEvidenceBundle | None:
        """Builds evidence bundle for a specific conclusion."""
        return self._evidence.query_evidence_for_conclusion(conclusion_id)

    def chat_with_evidence(
        self,
        query: str,
        peer_id: str | None = None,
        include_evidence: bool = False,
    ) -> tuple[str, ChatEvidenceBundle | None]:
        """Queries conclusions with optional verifiable evidence packaging."""
        return self._evidence.chat_with_evidence(
            query=query,
            peer_id=peer_id,
            include_evidence=include_evidence,
        )

    def get_stats(self) -> ConclusionEvidenceStats:
        """Retrieves graph topology and attribution counters."""
        return self._graph.get_stats()
