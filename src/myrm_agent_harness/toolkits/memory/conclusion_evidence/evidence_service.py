"""Chat evidence verification and packaging service."""

from __future__ import annotations

import threading

from myrm_agent_harness.toolkits.memory.conclusion_evidence.derivation_graph import (
    ConclusionDerivationGraphEngine,
)
from myrm_agent_harness.toolkits.memory.conclusion_evidence.models import (
    AttributedConclusion,
    ChatEvidenceBundle,
    MessageEvidenceItem,
    ToolCallEvidenceItem,
)


class ChatEvidenceService:
    """Provides on-demand evidence bundling and audit retrieval for agent conversations."""

    def __init__(self, graph_engine: ConclusionDerivationGraphEngine) -> None:
        self._graph: ConclusionDerivationGraphEngine = graph_engine
        self._messages: dict[str, MessageEvidenceItem] = {}
        self._tool_calls: list[ToolCallEvidenceItem] = []
        self._lock: threading.Lock = threading.Lock()

    def register_message_evidence(self, item: MessageEvidenceItem) -> None:
        """Stores a snapshot message snippet as verifiable provenance."""
        with self._lock:
            self._messages[item.message_id] = item

    def record_tool_call(self, tool_call: ToolCallEvidenceItem) -> None:
        """Appends a tool execution record as ground truth trace."""
        with self._lock:
            self._tool_calls.append(tool_call)

    def get_message_evidence(self, message_id: str) -> MessageEvidenceItem | None:
        """Retrieves single message evidence snippet."""
        with self._lock:
            return self._messages.get(message_id)

    def query_evidence_for_conclusion(self, conclusion_id: str) -> ChatEvidenceBundle | None:
        """Builds evidence bundle for a specific conclusion, linking its origin messages."""
        conclusion: AttributedConclusion | None = self._graph.get_conclusion(conclusion_id)
        if conclusion is None:
            return None

        with self._lock:
            matched_messages: list[MessageEvidenceItem] = []
            for mid in conclusion.evidence_message_ids:
                if mid in self._messages:
                    matched_messages.append(self._messages[mid])

            return ChatEvidenceBundle(
                conclusions=(conclusion,),
                messages=tuple(matched_messages),
                tool_calls=tuple(self._tool_calls[-5:]),
                reasoning_trace_id=f"trace_{conclusion_id}",
            )

    def chat_with_evidence(
        self,
        query: str,
        peer_id: str | None = None,
        include_evidence: bool = False,
    ) -> tuple[str, ChatEvidenceBundle | None]:
        """Queries conclusions with optional verifiable evidence packaging.

        When include_evidence is False, zero additional token overhead is incurred.
        """
        all_nodes: list[AttributedConclusion] = self._graph.get_all_conclusions()
        matched: list[AttributedConclusion] = []
        query_lower: str = query.lower()

        for c in all_nodes:
            if peer_id is not None and c.peer_id != peer_id:
                continue
            # Simple keyword matching for retrieval demonstration
            if any(token in c.content.lower() for token in query_lower.split()) or not query_lower:
                matched.append(c)

        if not matched:
            content_text = "No matching authoritative conclusions found."
        else:
            content_text = "; ".join(c.content for c in matched)

        if not include_evidence:
            return content_text, None

        with self._lock:
            matched_msg_ids: set[str] = {mid for c in matched for mid in c.evidence_message_ids}
            evidence_msgs: list[MessageEvidenceItem] = [
                self._messages[mid] for mid in matched_msg_ids if mid in self._messages
            ]

            bundle = ChatEvidenceBundle(
                conclusions=tuple(matched),
                messages=tuple(evidence_msgs),
                tool_calls=tuple(self._tool_calls[-5:]),
                reasoning_trace_id="trace_query_audit",
            )
            return content_text, bundle
