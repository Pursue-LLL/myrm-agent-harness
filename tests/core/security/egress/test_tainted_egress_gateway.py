"""Unit tests for transport-level TaintedEgressGateway."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.egress.tainted_gateway import (
    TaintedEgressBlockedException,
    TaintedEgressDecision,
    TaintedEgressGateway,
    is_current_egress_tainted,
    set_current_egress_tainted,
)


def test_clean_session_permits_any_egress():
    """An untainted session should freely connect to any external host."""
    gateway = TaintedEgressGateway(static_trusted_domains=["api.openai.com"])
    set_current_egress_tainted(False)

    decision, reason = gateway.evaluate_egress("github.com", port=443)
    assert decision == TaintedEgressDecision.ALLOW_CLEAN
    assert "clean" in reason.lower()

    # check_or_raise does not raise for clean session
    gateway.check_or_raise("github.com", port=443)


def test_tainted_session_blocks_unapproved_external_egress():
    """When marked as tainted, unapproved external hosts are strictly blocked."""
    gateway = TaintedEgressGateway(static_trusted_domains=["api.openai.com"])
    set_current_egress_tainted(True)
    assert is_current_egress_tainted() is True

    decision, reason = gateway.evaluate_egress("evil-attacker.org", port=443)
    assert decision == TaintedEgressDecision.BLOCKED_TAINTED
    assert "unapproved" in reason.lower()

    with pytest.raises(TaintedEgressBlockedException) as exc_info:
        gateway.check_or_raise("evil-attacker.org", port=443)

    err = exc_info.value
    assert err.host == "evil-attacker.org"
    assert err.port == 443
    user_msg = err.format_for_user()
    assert "Blocked outbound network connection to 'evil-attacker.org:443'" in user_msg
    assert "sensitive files or secrets" in user_msg


def test_tainted_session_permits_loopback_by_default():
    """Loopback connections (127.0.0.1, localhost) remain accessible under taint."""
    gateway = TaintedEgressGateway(allow_loopback=True)
    set_current_egress_tainted(True)

    for host in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
        decision, _ = gateway.evaluate_egress(host, port=8080)
        assert decision == TaintedEgressDecision.ALLOW_WHITELISTED
        gateway.check_or_raise(host, port=8080)


def test_tainted_session_permits_static_and_subdomain_allowlist():
    """Pre-configured static trusted domains and their subdomains are permitted."""
    gateway = TaintedEgressGateway(static_trusted_domains=["myrm.ai", "api.anthropic.com"])
    set_current_egress_tainted(True)

    # Exact match
    decision, _ = gateway.evaluate_egress("myrm.ai", port=443)
    assert decision == TaintedEgressDecision.ALLOW_WHITELISTED

    # Subdomain match
    decision, _ = gateway.evaluate_egress("sandbox.myrm.ai", port=443)
    assert decision == TaintedEgressDecision.ALLOW_WHITELISTED

    decision, _ = gateway.evaluate_egress("api.anthropic.com", port=443)
    assert decision == TaintedEgressDecision.ALLOW_WHITELISTED

    # Unrelated domain blocked
    decision, _ = gateway.evaluate_egress("fake-myrm.ai.evil.com", port=443)
    assert decision == TaintedEgressDecision.BLOCKED_TAINTED


def test_session_level_domain_trust_lifecycle():
    """Dynamic session-level trust allows unapproved domains upon user approval."""
    gateway = TaintedEgressGateway()
    set_current_egress_tainted(True)

    # Initially blocked
    decision, _ = gateway.evaluate_egress("docs.python.org", port=443)
    assert decision == TaintedEgressDecision.BLOCKED_TAINTED

    # User clicks 'Trust for this session'
    gateway.add_session_trusted_domain("docs.python.org")
    assert gateway.is_domain_trusted("docs.python.org") is True

    decision, reason = gateway.evaluate_egress("docs.python.org", port=443)
    assert decision == TaintedEgressDecision.ALLOW_WHITELISTED
    assert "trusted" in reason.lower()
    gateway.check_or_raise("docs.python.org", port=443)

    # Subdomain of trusted session domain
    assert gateway.is_domain_trusted("peps.docs.python.org") is True

    # Revoke trust
    assert gateway.remove_session_trusted_domain("docs.python.org") is True
    decision, _ = gateway.evaluate_egress("docs.python.org", port=443)
    assert decision == TaintedEgressDecision.BLOCKED_TAINTED


def test_mask_url_for_audit_strips_credentials_and_tokens():
    """URL masking ensures passwords and query tokens never leak into audit logs."""
    url = "https://admin:supersecret@api.example.com/v1/checkout?token=xyz123&session_id=abc&key=my_api_key_456"
    sanitized = TaintedEgressGateway.mask_url_for_audit(url)

    assert "supersecret" not in sanitized
    assert "xyz123" not in sanitized
    assert "my_api_key_456" not in sanitized
    assert "***:***@" in sanitized
    assert "token=***" in sanitized
    assert "key=***" in sanitized
    assert "session_id=abc" in sanitized  # non-secret query preserved


def test_extract_host_from_url_helper():
    """Test extracting host from various URL formats."""
    assert TaintedEgressGateway.extract_host_from_url("https://sub.domain.org/path") == "sub.domain.org"
    assert TaintedEgressGateway.extract_host_from_url("http://localhost:8080/test") == "localhost"
    assert TaintedEgressGateway.extract_host_from_url("api.github.com/v1") == "api.github.com"
    assert TaintedEgressGateway.extract_host_from_url("") == ""
