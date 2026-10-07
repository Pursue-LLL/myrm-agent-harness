# [POS]: tests.unit.toolkits.memory.test_peer_gateway_suite
# [INPUT]: myrm_agent_harness.toolkits.memory (peer_gateway suite)
# [OUTPUT]: Pytest unit test cases for deterministic peer resolver and anti-cross-contamination gateway

"""Unit tests for Multi-Channel Peer Alias and Anti-Cross-Contamination Gateway Suite.

Validates deterministic resolution, pinned primary peers, adaptive hash escalation, and boundary gates.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory import (
    AntiCrossContaminationGateway,
    ChannelType,
    DeterministicPeerResolver,
    GatewayPeerAliasConfig,
    HashEscalationEngine,
)


def test_hash_escalation_clean_and_adaptive_expansion():
    """Verify identifier cleaning and stepwise collision length escalation."""
    cleaned = HashEscalationEngine.clean_identifier("User.Alice@Office-Work 2026!")
    assert cleaned == "user_alice_office-work_2026"

    # Default collision-free resolution generates 8-char suffix
    collision_registry: set[str] = set()
    candidate_1, escalated_1 = HashEscalationEngine.escalate_hash_suffix(
        raw_id="feishu_ou_999",
        collision_registry=collision_registry,
        prefix="peer_",
    )
    assert escalated_1 is False
    assert candidate_1.startswith("peer_feishu_ou_999_")
    assert len(candidate_1.split("_")[-1]) == 8

    # Simulate collision on the first 8-char candidate
    collision_registry.add(candidate_1)
    candidate_2, escalated_2 = HashEscalationEngine.escalate_hash_suffix(
        raw_id="feishu_ou_999",
        collision_registry=collision_registry,
        prefix="peer_",
    )
    assert escalated_2 is True
    # Escalated to 12-char suffix
    assert len(candidate_2.split("_")[-1]) == 12
    assert candidate_2 != candidate_1


def test_deterministic_resolver_pinned_primary_mode():
    """Verify pin_user_peer enforces single-user master identity across all channels."""
    config = GatewayPeerAliasConfig(pin_user_peer="peer_master_admin")
    resolver = DeterministicPeerResolver(config)

    res_desktop = resolver.resolve_peer(ChannelType.DESKTOP, "local_session_01")
    assert res_desktop.canonical_peer_id == "peer_master_admin"
    assert res_desktop.is_pinned is True
    assert res_desktop.channel_type == ChannelType.DESKTOP

    res_web = resolver.resolve_peer(ChannelType.WEB, "browser_cookie_99")
    assert res_web.canonical_peer_id == "peer_master_admin"
    assert res_web.is_pinned is True


def test_deterministic_resolver_alias_mapping():
    """Verify multi-channel aliases merge different client devices into identical peer."""
    config = GatewayPeerAliasConfig(
        user_peer_aliases={
            "desktop:workstation_10": "peer_alice",
            "feishu:ou_alice_corp": "peer_alice",
            "mobile_iphone": "peer_alice",
        }
    )
    resolver = DeterministicPeerResolver(config)

    # 1. Desktop match via channel-qualified key
    res_desktop = resolver.resolve_peer(ChannelType.DESKTOP, "workstation_10")
    assert res_desktop.canonical_peer_id == "peer_alice"
    assert res_desktop.alias_matched is True
    assert res_desktop.is_pinned is False

    # 2. Feishu match
    res_feishu = resolver.resolve_peer(ChannelType.FEISHU, "ou_alice_corp")
    assert res_feishu.canonical_peer_id == "peer_alice"
    assert res_feishu.alias_matched is True

    # 3. Raw alias match
    res_mobile = resolver.resolve_peer(ChannelType.TELEGRAM, "mobile_iphone")
    assert res_mobile.canonical_peer_id == "peer_alice"
    assert res_mobile.alias_matched is True

    # 4. Unknown user falls back to hash escalation
    res_unknown = resolver.resolve_peer(ChannelType.WEB, "stranger_404")
    assert res_unknown.canonical_peer_id.startswith("peer_web_stranger_404_")
    assert res_unknown.alias_matched is False

    # 5. Dynamic alias registration
    resolver.register_alias("slack:U98765", "peer_bob")
    res_dyn = resolver.resolve_peer(ChannelType.SLACK, "U98765")
    assert res_dyn.canonical_peer_id == "peer_bob"
    assert res_dyn.alias_matched is True


def test_anti_cross_contamination_gateway_boundaries():
    """Verify strict tenant and peer boundary enforcement preventing memory contamination."""
    config = GatewayPeerAliasConfig(
        allowed_collaborator_peers=["agent_general_assistant", "agent_reviewer"],
        user_peer_aliases={"desktop:alice": "peer_alice", "desktop:bob": "peer_bob"},
    )
    gateway = AntiCrossContaminationGateway(config=config)

    # 1. Self access allowed
    self_check = gateway.validate_session_peer_boundary("peer_alice", "peer_alice")
    assert self_check.allowed is True
    assert self_check.violation_reason is None

    # 2. Access to public collaborator/agent allowed
    collab_check = gateway.validate_session_peer_boundary("peer_alice", "agent_reviewer")
    assert collab_check.allowed is True

    # 3. Cross-peer unauthorized memory snooping blocked
    cross_check = gateway.validate_session_peer_boundary("peer_alice", "peer_bob")
    assert cross_check.allowed is False
    assert "Cross-peer contamination blocked" in (cross_check.violation_reason or "")

    # 4. Atomic resolve and verify pass
    identity, check_res = gateway.resolve_and_verify(ChannelType.DESKTOP, "alice", "agent_general_assistant")
    assert identity.canonical_peer_id == "peer_alice"
    assert check_res.allowed is True
