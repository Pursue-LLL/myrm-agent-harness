"""Unit tests for localhost anti-DNS-rebinding and origin anti-hijack guard suite."""

from __future__ import annotations

from myrm_agent_harness.core.security.localhost_anti_hijack import (
    HostOriginGuard,
    HostOriginPolicy,
    SetupTokenManager,
)


def test_setup_token_generation_and_consumption() -> None:
    """Test generating a single-use setup token and consuming it for session cookie."""
    manager = SetupTokenManager(cookie_name="myrm_session")
    record = manager.generate_token(ttl_seconds=60, client_binding="test-client-1")

    assert record.token is not None
    assert len(record.token) >= 32
    assert not record.is_consumed

    # First consumption succeeds
    success, msg, cookie_spec = manager.consume_token(
        record.token, client_binding="test-client-1"
    )
    assert success is True
    assert msg == "Token consumed successfully"
    assert cookie_spec is not None
    assert cookie_spec.cookie_name == "myrm_session"
    assert cookie_spec.httponly is True
    assert cookie_spec.samesite == "strict"

    # Session is active
    assert manager.validate_session(cookie_spec.session_id) is True

    # Re-consumption fails (one-time invariant)
    success2, msg2, cookie_spec2 = manager.consume_token(record.token)
    assert success2 is False
    assert "already been consumed" in msg2
    assert cookie_spec2 is None


def test_setup_token_client_binding_mismatch() -> None:
    """Test that client binding mismatch rejects token consumption."""
    manager = SetupTokenManager()
    record = manager.generate_token(ttl_seconds=60, client_binding="desktop-instance-a")

    success, msg, cookie_spec = manager.consume_token(
        record.token, client_binding="desktop-instance-b"
    )
    assert success is False
    assert "Client binding mismatch" in msg
    assert cookie_spec is None


def test_setup_token_expiry() -> None:
    """Test that expired tokens cannot be consumed."""
    manager = SetupTokenManager()
    record = manager.generate_token(ttl_seconds=-1)  # Immediately expired

    success, msg, cookie_spec = manager.consume_token(record.token)
    assert success is False
    assert "expired" in msg
    assert cookie_spec is None


def test_session_lifecycle_and_cleanup() -> None:
    """Test session validation, revocation, and cleanup."""
    manager = SetupTokenManager(cookie_max_age=1)
    record = manager.generate_token(ttl_seconds=60)
    _, _, cookie_spec = manager.consume_token(record.token)
    assert cookie_spec is not None

    session_id = cookie_spec.session_id
    assert manager.validate_session(session_id) is True

    # Revoke
    assert manager.revoke_session(session_id) is True
    assert manager.validate_session(session_id) is False

    # Second revoke returns False
    assert manager.revoke_session(session_id) is False


def test_host_guard_dns_rebinding_interception() -> None:
    """Test Host header inspection blocks external domains attempting DNS rebinding."""
    guard = HostOriginGuard()

    # Legitimate local hosts
    assert guard.is_host_allowed("127.0.0.1") is True
    assert guard.is_host_allowed("127.0.0.1:8000") is True
    assert guard.is_host_allowed("localhost") is True
    assert guard.is_host_allowed("localhost:5173") is True
    assert guard.is_host_allowed("[::1]:8000") is True

    # Malicious external domains (e.g. attacker resolved attacker.com to 127.0.0.1)
    assert guard.is_host_allowed("attacker.com") is False
    assert guard.is_host_allowed("attacker.com:8000") is False
    assert guard.is_host_allowed("evil.local:8000") is False
    assert guard.is_host_allowed("192.168.1.100:8000") is False


def test_origin_guard_cross_origin_interception() -> None:
    """Test Origin header inspection blocks unauthorized cross-origin requests."""
    guard = HostOriginGuard()

    # Legitimate local origins
    assert guard.is_origin_allowed(None) is True
    assert guard.is_origin_allowed("http://localhost:5173") is True
    assert guard.is_origin_allowed("http://127.0.0.1:8000") is True
    assert guard.is_origin_allowed("tauri://localhost") is True

    # Malicious origins from web pages
    assert guard.is_origin_allowed("https://attacker.com") is False
    assert guard.is_origin_allowed("http://malicious-page.xyz:3000") is False


def test_verify_request_end_to_end() -> None:
    """Test verify_request performs holistic check on Host, Origin, and Referer."""
    guard = HostOriginGuard()

    # Valid local request
    res_valid = guard.verify_request(
        host="localhost:8000",
        origin="http://localhost:5173",
        referer="http://localhost:5173/dashboard",
        client_ip="127.0.0.1",
    )
    assert res_valid.is_allowed is True
    assert res_valid.status == "allowed"

    # DNS rebinding attack
    res_rebinding = guard.verify_request(
        host="evil-rebinding.com:8000",
        origin="http://localhost:8000",
        client_ip="127.0.0.1",
    )
    assert res_rebinding.is_allowed is False
    assert res_rebinding.status == "rejected_host"

    # Cross-site script attack
    res_cors_attack = guard.verify_request(
        host="127.0.0.1:8000",
        origin="https://hacker.io",
        client_ip="127.0.0.1",
    )
    assert res_cors_attack.is_allowed is False
    assert res_cors_attack.status == "rejected_origin"

    # Malicious referer navigation without origin
    res_bad_referer = guard.verify_request(
        host="127.0.0.1:8000",
        origin=None,
        referer="https://phishing-site.com/exploit",
        client_ip="127.0.0.1",
    )
    assert res_bad_referer.is_allowed is False
    assert res_bad_referer.status == "rejected_referer"


def test_custom_host_origin_policy() -> None:
    """Test custom HostOriginPolicy with enterprise intranet host and custom origins."""
    policy = HostOriginPolicy(
        allowed_hosts=("internal-hub.corp", "localhost"),
        allowed_origins=("https://internal-hub.corp",),
        allow_null_origin=True,
        enforce_strict_mode=True,
    )
    guard = HostOriginGuard(policy=policy)

    assert guard.is_host_allowed("internal-hub.corp:8443") is True
    assert guard.is_host_allowed("127.0.0.1") is False  # not in custom whitelist
    assert guard.is_origin_allowed("null") is True  # allow_null_origin=True
    assert guard.is_origin_allowed("https://internal-hub.corp") is True
    assert guard.is_origin_allowed("http://localhost:3000") is False

