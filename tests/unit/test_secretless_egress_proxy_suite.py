"""Unit tests for Secretless Credential Egress Proxy and Placeholder Swap Suite."""

from __future__ import annotations

from myrm_agent_harness.core.security.secretless_egress_proxy import (
    PlaceholderRegistry,
    SwapOnAccessProxy,
)


def test_placeholder_registry_generation_and_revocation() -> None:
    """Test placeholder generation, lookup by host/token, and revocation."""
    registry = PlaceholderRegistry()
    spec = registry.register_credential(
        target_host="api.github.com",
        real_secret="ghp_real_secret_token_123456",
        auth_header_name="Authorization",
        auth_header_template="token {secret}",
    )

    assert spec.target_host == "api.github.com"
    assert spec.placeholder.startswith("myrm_cred_")
    assert registry.is_placeholder(spec.placeholder) is True
    assert registry.is_placeholder("random_unregistered_token") is False

    # Lookup by host and by placeholder
    by_host = registry.get_by_host("https://api.github.com/user")
    assert by_host is not None
    assert by_host.real_secret == "ghp_real_secret_token_123456"

    by_token = registry.get_by_placeholder(spec.placeholder)
    assert by_token is not None
    assert by_token.target_host == "api.github.com"

    # Revocation
    assert registry.revoke_credential("api.github.com") is True
    assert registry.get_by_host("api.github.com") is None
    assert registry.get_by_placeholder(spec.placeholder) is None


def test_swap_on_access_legitimate_placeholder_replacement() -> None:
    """Test that requests directed to bound host have placeholder swapped with real secret."""
    registry = PlaceholderRegistry()
    spec = registry.register_credential(
        target_host="api.github.com",
        real_secret="ghp_super_secret_github_key",
    )
    proxy = SwapOnAccessProxy(registry=registry)

    # Request containing placeholder sent to legitimate target host
    req_headers = {"Authorization": f"Bearer {spec.placeholder}", "User-Agent": "myrm-client"}
    result = proxy.inspect_and_swap(
        target_host="api.github.com",
        path="/user/repos",
        method="GET",
        headers=req_headers,
    )

    assert result.is_allowed is True
    assert result.status_code == 200
    assert "Authorization" in result.headers_to_inject
    assert result.headers_to_inject["Authorization"] == "Bearer ghp_super_secret_github_key"
    assert spec.placeholder not in result.headers_to_inject["Authorization"]

    # Verify audit event
    events = proxy.get_audit_events()
    assert len(events) == 1
    assert events[0].is_swapped is True
    assert events[0].is_blocked is False
    assert events[0].target_host == "api.github.com"


def test_cross_domain_exfiltration_blocked_with_403() -> None:
    """Test that malicious scripts attempting to send placeholder to evil host are blocked."""
    registry = PlaceholderRegistry()
    spec = registry.register_credential(
        target_host="api.github.com",
        real_secret="ghp_sensitive_secret",
    )
    proxy = SwapOnAccessProxy(registry=registry)

    # Malicious script sends placeholder to attacker server
    malicious_headers = {"X-Exfiltrate-Token": spec.placeholder}
    result = proxy.inspect_and_swap(
        target_host="evil-attacker-dropzone.xyz",
        path="/collect_tokens",
        method="POST",
        headers=malicious_headers,
    )

    assert result.is_allowed is False
    assert result.status_code == 403
    assert "cross-domain exfiltration attempt blocked" in result.reason
    assert "ghp_sensitive_secret" not in result.reason  # Real secret never leaked in error

    # Verify blocked audit event
    events = proxy.get_audit_events()
    assert len(events) == 1
    assert events[0].is_blocked is True
    assert events[0].is_swapped is False
    assert "Cross-domain exfiltration blocked" in (events[0].block_reason or "")


def test_automatic_swap_on_access_without_placeholder() -> None:
    """Test transparent credential injection for secretless clients without env vars."""
    registry = PlaceholderRegistry()
    registry.register_credential(
        target_host="api.stripe.com",
        real_secret="sk_live_stripe_secret_12345",
        auth_header_name="Authorization",
        auth_header_template="Bearer {secret}",
    )
    proxy = SwapOnAccessProxy(registry=registry)

    # Client sends clean request without Authorization header
    result = proxy.inspect_and_swap(
        target_host="api.stripe.com",
        path="/v1/charges",
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    assert result.is_allowed is True
    assert result.status_code == 200
    assert result.headers_to_inject["Authorization"] == "Bearer sk_live_stripe_secret_12345"


def test_normal_unauthenticated_traffic_passes_cleanly() -> None:
    """Test normal non-credentialed traffic to arbitrary domains passes without headers."""
    registry = PlaceholderRegistry()
    proxy = SwapOnAccessProxy(registry=registry)

    result = proxy.inspect_and_swap(
        target_host="news.ycombinator.com",
        path="/",
        method="GET",
        headers={"Accept": "text/html"},
    )
    assert result.is_allowed is True
    assert result.status_code == 200
    assert len(result.headers_to_inject) == 0
