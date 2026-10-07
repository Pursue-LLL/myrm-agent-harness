from __future__ import annotations

import time
import uuid
from collections import defaultdict
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.cross_agent_communication_graph_types import (
    AgentCommunicationEdge,
    CausalPhaseSummary,
    CommunicationInteractionKind,
    MessageDurability,
    PrunedContextResult,
)


class CrossAgentCommunicationGraphEngine:
    """Runtime engine for cross-agent communication causal DAG tracing and phase-end ephemeral pruning."""

    def __init__(self) -> None:
        self._edges: dict[str, AgentCommunicationEdge] = {}
        self._phase_edges: defaultdict[str, list[str]] = defaultdict(list)
        self._pruned_phases: set[str] = set()
        self._phase_summaries: dict[str, CausalPhaseSummary] = {}

    def record_communication(
        self,
        sender_agent_id: str,
        receiver_agent_id: str,
        content: str,
        interaction_kind: CommunicationInteractionKind = CommunicationInteractionKind.NEGOTIATION,
        durability: MessageDurability = MessageDurability.EPHEMERAL,
        phase_tag: str = "default_phase",
        causal_parent_edge_id: str | None = None,
    ) -> AgentCommunicationEdge:
        """Record an active directed communication edge between agents."""
        edge_id = f"edge_{uuid.uuid4().hex[:8]}"
        edge = AgentCommunicationEdge(
            edge_id=edge_id,
            sender_agent_id=sender_agent_id,
            receiver_agent_id=receiver_agent_id,
            interaction_kind=interaction_kind,
            durability=durability,
            phase_tag=phase_tag,
            content_payload=content.strip(),
            causal_parent_edge_id=causal_parent_edge_id,
            timestamp_ms=int(time.time() * 1000),
        )
        self._edges[edge_id] = edge
        self._phase_edges[phase_tag].append(edge_id)
        return edge

    def get_edge(self, edge_id: str) -> AgentCommunicationEdge | None:
        """Lookup a communication edge by ID."""
        return self._edges.get(edge_id)

    def get_phase_edges(self, phase_tag: str) -> list[AgentCommunicationEdge]:
        """Retrieve all edges recorded under a specific collaboration phase."""
        edge_ids = self._phase_edges.get(phase_tag, [])
        return [self._edges[eid] for eid in edge_ids if eid in self._edges]

    def get_causal_chain(self, edge_id: str) -> list[AgentCommunicationEdge]:
        """Trace backward from an edge to discover its full ancestor causal chain in chronological order."""
        chain: list[AgentCommunicationEdge] = []
        curr_id: str | None = edge_id
        visited: set[str] = set()

        while curr_id and curr_id in self._edges:
            if curr_id in visited:
                break  # Cycle defense
            visited.add(curr_id)
            edge = self._edges[curr_id]
            chain.append(edge)
            curr_id = edge.causal_parent_edge_id

        chain.reverse()
        return chain

    def prune_phase_communication(
        self,
        phase_tag: str,
        decision_conclusion: str | None = None,
        durable_artifacts: Sequence[str] | None = None,
    ) -> PrunedContextResult:
        """Prune ephemeral chatter from a completed phase and replace with a compact causal decision summary."""
        edges = self.get_phase_edges(phase_tag)
        if not edges:
            raise ValueError(f"Collaboration phase '{phase_tag}' has no recorded communication edges.")

        involved_agents = sorted({e.sender_agent_id for e in edges} | {e.receiver_agent_id for e in edges})
        ephemeral_edges = [e for e in edges if e.durability == MessageDurability.EPHEMERAL]
        durable_edges = [e for e in edges if e.durability == MessageDurability.DURABLE]

        # Token estimation: roughly 4 characters per token
        orig_char_count = sum(len(e.content_payload) for e in edges)
        orig_tokens_est = max(1, orig_char_count // 4)

        conclusion = (
            decision_conclusion.strip()
            if decision_conclusion
            else f"Phase completed with consensus reached among {', '.join(involved_agents)}."
        )
        artifacts_list = list(durable_artifacts or [])

        summary_lines = [
            f'<system_causal_collaboration_summary phase="{phase_tag}">',
            f"[COLLABORATING_AGENTS]: {', '.join(involved_agents)}",
            f"[CAUSAL_DECISION_CONCLUSION]: {conclusion}",
        ]
        if artifacts_list:
            summary_lines.append("[RETAINED_DELIVERABLES]:")
            for art in artifacts_list:
                summary_lines.append(f"  - {art}")

        summary_lines.extend([
            f"[EPHEMERAL_COMMUNICATION_PRUNED]: {len(ephemeral_edges)} temporary discussion turns safely pruned.",
            "</system_causal_collaboration_summary>",
        ])
        summary_xml = "\n".join(summary_lines)

        durable_chars = sum(len(e.content_payload) for e in durable_edges)
        remaining_chars = len(summary_xml) + durable_chars
        remaining_tokens_est = max(1, remaining_chars // 4)

        reduction_rate = max(0.0, (orig_tokens_est - remaining_tokens_est) / orig_tokens_est)

        phase_summary = CausalPhaseSummary(
            phase_tag=phase_tag,
            involved_agent_ids=involved_agents,
            total_edges_count=len(edges),
            ephemeral_edges_count=len(ephemeral_edges),
            pruned_tokens_estimate=orig_tokens_est - remaining_tokens_est,
            causal_decision_summary=summary_xml,
            durable_artifacts_retained=artifacts_list,
        )

        self._pruned_phases.add(phase_tag)
        self._phase_summaries[phase_tag] = phase_summary

        return PrunedContextResult(
            phase_tag=phase_tag,
            pruned_edges_count=len(ephemeral_edges),
            original_tokens_estimate=orig_tokens_est,
            remaining_tokens_estimate=remaining_tokens_est,
            token_reduction_rate=reduction_rate,
            rendered_causal_summary_block=summary_xml,
        )

    def render_active_context(self) -> str:
        """Render active global multi-agent context, folding pruned phases into causal summaries."""
        blocks: list[str] = []

        for phase_tag, edge_ids in self._phase_edges.items():
            if phase_tag in self._pruned_phases and phase_tag in self._phase_summaries:
                # 1. Include high-density summary
                blocks.append(self._phase_summaries[phase_tag].causal_decision_summary)
                # 2. Include durable deliverables from that phase
                for eid in edge_ids:
                    e = self._edges.get(eid)
                    if e and e.durability == MessageDurability.DURABLE:
                        blocks.append(f"[{e.sender_agent_id} -> {e.receiver_agent_id}] (DURABLE): {e.content_payload}")
            else:
                # Active unpruned phase: retain raw edges
                for eid in edge_ids:
                    e = self._edges.get(eid)
                    if e:
                        blocks.append(
                            f"[{e.sender_agent_id} -> {e.receiver_agent_id}] ({e.interaction_kind.value}): "
                            f"{e.content_payload}"
                        )

        return "\n\n".join(blocks)
