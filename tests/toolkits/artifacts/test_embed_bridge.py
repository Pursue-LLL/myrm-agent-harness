from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.artifacts.embed_bridge import (
    EmbedSecurityPolicy,
    HostContextBridgeEngine,
    HostContextSnapshot,
)


def test_validate_origin_wildcard_and_exact() -> None:
    engine = HostContextBridgeEngine()

    # 1. Wildcard policy allows all
    wildcard_policy = EmbedSecurityPolicy(allowed_origins=["*"])
    assert engine.validate_origin("https://any-domain.com", wildcard_policy)
    assert engine.validate_origin("http://localhost:3000", wildcard_policy)
    assert not engine.validate_origin("", wildcard_policy)

    # 2. Strict exact match policy
    strict_policy = EmbedSecurityPolicy(
        allowed_origins=["https://crm.example.com", "https://app.corp.internal/"]
    )
    assert engine.validate_origin("https://crm.example.com", strict_policy)
    assert engine.validate_origin("https://crm.example.com/", strict_policy)
    assert engine.validate_origin("https://app.corp.internal", strict_policy)
    assert not engine.validate_origin("https://evil.com", strict_policy)

    # 3. Wildcard subdomain policy
    subdomain_policy = EmbedSecurityPolicy(allowed_origins=["*.acme.org"])
    assert engine.validate_origin("https://portal.acme.org", subdomain_policy)
    assert engine.validate_origin("https://billing.prod.acme.org", subdomain_policy)
    assert not engine.validate_origin("https://fakeacme.org", subdomain_policy)
    assert not engine.validate_origin("https://other.com", subdomain_policy)


def test_compile_context_prompt_formatting() -> None:
    engine = HostContextBridgeEngine()

    snapshot = HostContextSnapshot(
        origin="https://shop.example.com",
        current_url="https://shop.example.com/orders/ORD-99812",
        page_title="Order Detail - Customer Support",
        selected_text="Item damaged during transit",
        form_fields={"order_id": "ORD-99812", "amount": "$199.00", "status": "shipped"},
        user_metadata={"user_role": "vip_customer"},
    )

    prompt = engine.compile_context_prompt(snapshot)
    assert "@host_context: External Host Webpage Snapshot" in prompt
    assert "https://shop.example.com/orders/ORD-99812" in prompt
    assert "Order Detail - Customer Support" in prompt
    assert "Item damaged during transit" in prompt
    assert "order_id: ORD-99812" in prompt
    assert "user_role: vip_customer" in prompt

    # When form capture is disabled
    no_form_policy = EmbedSecurityPolicy(allow_form_capture=False)
    filtered_prompt = engine.compile_context_prompt(snapshot, policy=no_form_policy)
    assert "Active Form Fields" not in filtered_prompt
    assert "Item damaged during transit" in filtered_prompt


def test_inject_context_success_and_permission_error() -> None:
    engine = HostContextBridgeEngine()
    session_id = "session_embed_test_01"

    allowed_policy = EmbedSecurityPolicy(allowed_origins=["https://dashboard.mycompany.com"])

    snapshot = HostContextSnapshot(
        origin="https://dashboard.mycompany.com",
        current_url="https://dashboard.mycompany.com/analytics",
        page_title="Q3 Performance Metrics",
    )

    injected = engine.inject_context(session_id, snapshot, allowed_policy)
    assert injected.session_id == session_id
    assert "Q3 Performance Metrics" in injected.context_text

    latest = engine.get_latest_context(session_id)
    assert latest is not None
    assert latest.snapshot.origin == "https://dashboard.mycompany.com"

    # Reject disallowed origin
    unauthorized_snapshot = HostContextSnapshot(
        origin="https://unauthorized-site.com",
        current_url="https://unauthorized-site.com/exploit",
    )
    with pytest.raises(PermissionError, match="not permitted by embed security policy"):
        engine.inject_context(session_id, unauthorized_snapshot, allowed_policy)
