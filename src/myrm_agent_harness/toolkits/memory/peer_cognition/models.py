# [POS]: myrm_agent_harness.toolkits.memory.peer_cognition.models
# [INPUT]: None (Standard library & Pydantic)
# [OUTPUT]: PeerType, PeerRelationKind, PeerIdentity, PeerRelationEdge, PeerPersonaCard, PeerCognitionProjection

"""Domain models for peer-centric social cognition entity graph and agent persona cards.

P0 delivery for Item 110 in topic_01 memory roadmap.
Transitions agent memory from isolated, unowned facts to a structured social cognition
network where every fact, preference, and role is anchored to an evolving Peer identity.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class PeerType(StrEnum):
    """Categorical type of social cognition peer entity."""

    USER_PEER = "user_peer"
    AGENT_PEER = "agent_peer"
    PROJECT_PEER = "project_peer"
    REVIEWER_PEER = "reviewer_peer"


class PeerRelationKind(StrEnum):
    """Types of semantic and cognitive relations connecting peers and entities."""

    ASSERTS = "asserts"
    APPROVES = "approves"
    COLLABORATES_WITH = "collaborates_with"
    GOVERNS = "governs"
    DEPENDS_ON = "depends_on"


class PeerIdentity(BaseModel):
    """Persistent identity representation of a social cognition participant."""

    peer_id: str = Field(description="Unique system identifier for the peer")
    peer_type: PeerType = Field(description="Participant category")
    display_name: str = Field(description="Human or agent readable name")
    role_title: str = Field(default="", description="Functional role (e.g. Lead Architect, QA Reviewer)")
    avatar_or_icon: str = Field(default="", description="Visual icon or avatar URI")
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_seen_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class PeerRelationEdge(BaseModel):
    """Directed social cognition edge associating a peer to another peer or fact entity."""

    edge_id: str = Field(description="Unique edge identifier")
    source_peer_id: str = Field(description="Originating peer id")
    target_entity_id: str = Field(description="Target entity or peer id")
    target_is_peer: bool = Field(default=False, description="Whether target is another peer")
    relation_kind: PeerRelationKind = Field(description="Semantic relational verb")
    context_note: str = Field(default="", description="Optional situational context or rationale")
    weight: float = Field(default=1.0, description="Confidence or strength weight between 0.0 and 1.0")
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class PeerPersonaCard(BaseModel):
    """Curated, self-evolving standing persona card for a peer participant."""

    peer_id: str = Field(description="Associated peer identifier")
    peer_type: PeerType = Field(description="Peer categorical type")
    display_name: str = Field(description="Display label of peer")
    core_responsibilities: list[str] = Field(
        default_factory=list, description="Primary duties, boundaries, or specialization areas"
    )
    decision_style: str = Field(
        default="balanced", description="Decision risk tolerance and behavioral style"
    )
    standing_preferences: dict[str, str] = Field(
        default_factory=dict, description="Persistent preference key-value pairs"
    )
    interaction_count: int = Field(default=0, description="Total recorded interactions or collaborations")
    success_rate: float = Field(default=1.0, description="Task success rate when collaborating with this peer")
    trust_score: float = Field(default=1.0, description="Trust evaluation score between 0.0 and 1.0")
    summary_digest: str = Field(
        default="", description="Compact natural language summary (<150 words) for zero-overhead prompt injection"
    )
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class PeerCognitionProjection(BaseModel):
    """Low-token formatted context block ready for LLM prompt injection."""

    formatted_prompt_block: str = Field(description="Rendered markdown block describing relevant peer profiles")
    token_cost_estimate: int = Field(default=0, description="Estimated token overhead of injected context")
    targeted_peers: list[str] = Field(default_factory=list, description="List of peer_ids included in projection")
