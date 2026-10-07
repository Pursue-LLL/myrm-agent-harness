"""Types and models for cross agent communication graph.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- CommunicationInteractionKind: Categorical kind of cross-agent communication interaction.
- MessageDurability: Lifecycle durability classification for agent messages.
- AgentCommunicationEdge: An active directed communication edge in the runtime graph.
- CausalPhaseSummary: Consolidated causal summary synthesized upon phase conclusion.
- PrunedContextResult: Outcome report of phase-end communication context pruning.

[POS]
Types and models for cross agent communication graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CommunicationInteractionKind(StrEnum):
    """Categorical kind of cross-agent communication interaction."""

    DELEGATION = "delegation"
    PEER_CRITIQUE = "peer_critique"
    NEGOTIATION = "negotiation"
    BROADCAST = "broadcast"
    STATUS_UPDATE = "status_update"


class MessageDurability(StrEnum):
    """Lifecycle durability classification for agent messages."""

    EPHEMERAL = "ephemeral"
    DURABLE = "durable"


@dataclass(frozen=True, slots=True)
class AgentCommunicationEdge:
    """An active directed communication edge in the runtime graph."""

    edge_id: str
    sender_agent_id: str
    receiver_agent_id: str
    interaction_kind: CommunicationInteractionKind
    durability: MessageDurability
    phase_tag: str
    content_payload: str
    causal_parent_edge_id: str | None = None
    timestamp_ms: int = 0


@dataclass(frozen=True, slots=True)
class CausalPhaseSummary:
    """Consolidated causal summary synthesized upon phase conclusion."""

    phase_tag: str
    involved_agent_ids: list[str]
    total_edges_count: int
    ephemeral_edges_count: int
    pruned_tokens_estimate: int
    causal_decision_summary: str
    durable_artifacts_retained: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PrunedContextResult:
    """Outcome report of phase-end communication context pruning."""

    phase_tag: str
    pruned_edges_count: int
    original_tokens_estimate: int
    remaining_tokens_estimate: int
    token_reduction_rate: float
    rendered_causal_summary_block: str
