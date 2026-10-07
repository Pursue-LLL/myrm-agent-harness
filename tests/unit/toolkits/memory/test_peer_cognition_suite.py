# [POS]: tests/unit/toolkits/memory/test_peer_cognition_suite.py
# [INPUT]: myrm_agent_harness.toolkits.memory.peer_cognition
# [OUTPUT]: Unit tests for Peer-Centric Social Cognition Entity Graph and Agent Persona Card Suite (Item 110)

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.peer_cognition import (
    PeerCognitionGraphStore,
    PeerIdentity,
    PeerPersonaCardEngine,
    PeerRelationEdge,
    PeerRelationKind,
    PeerType,
)


def test_peer_registration_and_query() -> None:
    """Validate registering distinct peer types and querying by type."""
    store = PeerCognitionGraphStore()

    user_peer = PeerIdentity(
        peer_id="user_alice",
        peer_type=PeerType.USER_PEER,
        display_name="Alice",
        role_title="Lead Architect",
    )
    agent_peer = PeerIdentity(
        peer_id="agent_coder",
        peer_type=PeerType.AGENT_PEER,
        display_name="CoderBot",
        role_title="Backend Implementer",
    )
    reviewer_peer = PeerIdentity(
        peer_id="reviewer_bob",
        peer_type=PeerType.REVIEWER_PEER,
        display_name="Bob",
        role_title="Security Auditor",
    )
    project_peer = PeerIdentity(
        peer_id="proj_myrm",
        peer_type=PeerType.PROJECT_PEER,
        display_name="Myrm Core",
        role_title="Agent Harness Framework",
    )

    store.register_peer(user_peer)
    store.register_peer(agent_peer)
    store.register_peer(reviewer_peer)
    store.register_peer(project_peer)

    # 1. Total count
    assert len(store.list_peers()) == 4

    # 2. Query by type
    agents = store.list_peers(PeerType.AGENT_PEER)
    assert len(agents) == 1
    assert agents[0].peer_id == "agent_coder"

    users = store.list_peers(PeerType.USER_PEER)
    assert len(users) == 1
    assert users[0].display_name == "Alice"

    # 3. Get single peer
    fetched = store.get_peer("reviewer_bob")
    assert fetched is not None
    assert fetched.role_title == "Security Auditor"


def test_relational_edge_indexing_and_fact_tracing() -> None:
    """Validate graph relational edges, entity tracing, and collaborator discovery."""
    store = PeerCognitionGraphStore()

    alice = PeerIdentity(peer_id="user_alice", peer_type=PeerType.USER_PEER, display_name="Alice")
    coder = PeerIdentity(peer_id="agent_coder", peer_type=PeerType.AGENT_PEER, display_name="CoderBot")
    reviewer = PeerIdentity(peer_id="reviewer_bob", peer_type=PeerType.REVIEWER_PEER, display_name="Bob")
    store.register_peer(alice)
    store.register_peer(coder)
    store.register_peer(reviewer)

    # Alice asserts an architectural decision
    edge_assert = PeerRelationEdge(
        edge_id="edge_1",
        source_peer_id="user_alice",
        target_entity_id="fact_use_fastapi_and_pydantic",
        target_is_peer=False,
        relation_kind=PeerRelationKind.ASSERTS,
        context_note="Adopt FastAPI and Pydantic v2 as architectural standard",
        weight=1.0,
    )
    # Reviewer approves that decision
    edge_approve = PeerRelationEdge(
        edge_id="edge_2",
        source_peer_id="reviewer_bob",
        target_entity_id="fact_use_fastapi_and_pydantic",
        target_is_peer=False,
        relation_kind=PeerRelationKind.APPROVES,
        context_note="Security review passed for FastAPI async stack",
        weight=0.95,
    )
    # Alice collaborates with CoderBot
    edge_collab = PeerRelationEdge(
        edge_id="edge_3",
        source_peer_id="user_alice",
        target_entity_id="agent_coder",
        target_is_peer=True,
        relation_kind=PeerRelationKind.COLLABORATES_WITH,
        context_note="Pair programming on core harness",
        weight=1.0,
    )

    store.add_edge(edge_assert)
    store.add_edge(edge_approve)
    store.add_edge(edge_collab)

    # 1. Trace who asserted fact
    asserters = store.get_peers_connected_to_entity(
        "fact_use_fastapi_and_pydantic", relation_kind=PeerRelationKind.ASSERTS
    )
    assert len(asserters) == 1
    assert asserters[0][0].peer_id == "user_alice"

    # 2. Trace who approved fact
    approvers = store.get_peers_connected_to_entity(
        "fact_use_fastapi_and_pydantic", relation_kind=PeerRelationKind.APPROVES
    )
    assert len(approvers) == 1
    assert approvers[0][0].peer_id == "reviewer_bob"

    # 3. Find collaborators
    collabs = store.find_collaborators("user_alice")
    assert len(collabs) == 1
    assert collabs[0][0].peer_id == "agent_coder"

    # 4. Remove edge
    assert store.remove_edge("edge_1") is True
    assert len(store.get_peers_connected_to_entity("fact_use_fastapi_and_pydantic", PeerRelationKind.ASSERTS)) == 0


def test_persona_card_creation_and_evolution() -> None:
    """Validate persona card creation, incremental learning, and trust score smoothing."""
    store = PeerCognitionGraphStore()
    engine = PeerPersonaCardEngine(graph_store=store)

    peer = PeerIdentity(
        peer_id="user_charlie",
        peer_type=PeerType.USER_PEER,
        display_name="Charlie",
    )
    store.register_peer(peer)

    # 1. Initial card creation
    card = engine.create_or_update_card(
        peer_id="user_charlie",
        core_responsibilities=["Database Optimization", "Async Pipeline Tuning"],
        decision_style="rigorous_performance_first",
        standing_preferences={"db": "PostgreSQL", "orm": "SQLAlchemy2"},
    )
    assert card.peer_id == "user_charlie"
    assert card.interaction_count == 0
    assert card.trust_score == 1.0
    assert "Charlie" in card.summary_digest
    assert "PostgreSQL" in card.summary_digest

    # 2. Record successful interaction with preference evolution
    evolved_card = engine.record_interaction(
        peer_id="user_charlie",
        success=True,
        preference_deltas={"cache": "Redis", "db": "PostgreSQL-16"},
    )
    assert evolved_card.interaction_count == 1
    assert evolved_card.standing_preferences["cache"] == "Redis"
    assert evolved_card.standing_preferences["db"] == "PostgreSQL-16"
    assert evolved_card.trust_score >= 0.9

    # 3. Record failing interaction to test smooth trust decay
    degraded_card = engine.record_interaction(
        peer_id="user_charlie",
        success=False,
    )
    assert degraded_card.interaction_count == 2
    assert degraded_card.success_rate < 1.0
    assert degraded_card.trust_score < 1.0


def test_low_token_projection_and_multi_agent_alignment() -> None:
    """Validate compact context projection generation and role boundary alignment."""
    store = PeerCognitionGraphStore()
    engine = PeerPersonaCardEngine(graph_store=store)

    # Register user and agents
    store.register_peer(
        PeerIdentity(peer_id="user_lead", peer_type=PeerType.USER_PEER, display_name="LeadDev")
    )
    store.register_peer(
        PeerIdentity(peer_id="agent_arch", peer_type=PeerType.AGENT_PEER, display_name="ArchitectAgent")
    )
    store.register_peer(
        PeerIdentity(peer_id="agent_sec", peer_type=PeerType.AGENT_PEER, display_name="SecurityAgent")
    )

    engine.create_or_update_card(
        peer_id="user_lead",
        core_responsibilities=["Overall roadmap and PR approval"],
        decision_style="fast_iterative",
        standing_preferences={"language": "Python 3.13"},
    )
    engine.create_or_update_card(
        peer_id="agent_arch",
        core_responsibilities=["Modular decoupled boundaries", "Zero deep imports"],
        decision_style="strict_solid_principles",
        standing_preferences={"design": "SingleResponsibility"},
    )
    engine.create_or_update_card(
        peer_id="agent_sec",
        core_responsibilities=["PII sanitization", "Credential screening"],
        decision_style="fail_closed_zero_trust",
        standing_preferences={"auth": "mTLS"},
    )

    # 1. Generate low-token projection
    proj = engine.generate_projection(["user_lead", "agent_arch", "agent_sec"])
    assert proj.token_cost_estimate > 0
    assert len(proj.targeted_peers) == 3
    assert "[PEER SOCIAL COGNITION CONTEXT]" in proj.formatted_prompt_block
    assert "LeadDev" in proj.formatted_prompt_block
    assert "ArchitectAgent" in proj.formatted_prompt_block
    assert "SecurityAgent" in proj.formatted_prompt_block
    assert "Zero deep imports" in proj.formatted_prompt_block

    # 2. Empty projection safeguard
    empty_proj = engine.generate_projection(["nonexistent_peer"])
    assert empty_proj.token_cost_estimate == 0
    assert empty_proj.formatted_prompt_block == ""

    # 3. Multi-agent role boundary alignment
    role_map = engine.align_collaborator_roles(["agent_arch", "agent_sec"])
    assert "Modular decoupled boundaries" in role_map["agent_arch"]
    assert "PII sanitization" in role_map["agent_sec"]
