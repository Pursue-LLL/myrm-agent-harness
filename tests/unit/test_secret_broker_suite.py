"""Unit tests for Mechanical Credential Isolation and Zero-Context Secret Replacement suite.

[POS]
Harness core security test suite verifying egress-bound secret vault,
zero-context placeholder interception, and one-shot atomic operation grants.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.secret_broker import (
    AtomicGrantInvalidatedError,
    AtomicOperationGrantManager,
    EgressBoundSecretVault,
    EgressHostMismatchError,
    EgressSecretInterceptor,
    GrantStatus,
)


def test_vault_ingestion_and_resolution() -> None:
    vault = EgressBoundSecretVault()

    handle = vault.ingest_secret(
        secret_name="STRIPE_LIVE_KEY",
        secret_value="sk_live_super_secret_token_123",
        allowed_host="api.stripe.com",
    )

    assert handle.handle_id.startswith("hnd_")
    assert handle.placeholder == f"{{{{SECRET_VAULT:{handle.handle_id}}}}}"
    assert handle.allowed_host == "api.stripe.com"

    # Exact host resolution
    resolved = vault.resolve_secret_for_host(handle.handle_id, "api.stripe.com")
    assert resolved == "sk_live_super_secret_token_123"

    # Subdomain resolution
    resolved_sub = vault.resolve_secret_for_host(handle.handle_id, "sub.api.stripe.com")
    assert resolved_sub == "sk_live_super_secret_token_123"

    # Mismatched host raises EgressHostMismatchError
    with pytest.raises(EgressHostMismatchError) as exc_info:
        vault.resolve_secret_for_host(handle.handle_id, "evil-proxy.attacker.com")
    assert exc_info.value.handle_id == handle.handle_id
    assert exc_info.value.allowed_host == "api.stripe.com"
    assert exc_info.value.attempted_host == "evil-proxy.attacker.com"

    # Non-existent handle raises KeyError
    with pytest.raises(KeyError):
        vault.resolve_secret_for_host("hnd_nonexistent", "api.stripe.com")


def test_interceptor_egress_substitution() -> None:
    vault = EgressBoundSecretVault()
    stripe_h = vault.ingest_secret("STRIPE_KEY", "sk_live_abc123", "api.stripe.com")
    github_h = vault.ingest_secret("GITHUB_TOKEN", "ghp_securetoken999", "api.github.com")

    interceptor = EgressSecretInterceptor(vault)

    # Content with Stripe placeholder
    content = f"curl -H 'Authorization: Bearer {stripe_h.placeholder}' https://api.stripe.com/charges"
    assert interceptor.has_placeholders(content) is True
    assert interceptor.extract_handles(content) == [stripe_h.handle_id]

    # Authorized egress dispatch
    result = interceptor.inject_secrets(content, "api.stripe.com")
    assert result.authorized is True
    assert result.replacements_count == 1
    assert result.target_host == "api.stripe.com"
    assert "Bearer sk_live_abc123" in result.resolved_content
    assert stripe_h.placeholder not in result.resolved_content

    # Mismatched destination host blocks injection and raises error
    with pytest.raises(EgressHostMismatchError):
        interceptor.inject_secrets(content, "webhook.untrusted.org")

    # Content without placeholders
    plain_content = "Hello world, no secrets here."
    plain_result = interceptor.inject_secrets(plain_content, "api.stripe.com")
    assert plain_result.replacements_count == 0
    assert plain_result.resolved_content == plain_content

    # Multiple placeholders with cross-host failure
    mixed = f"Stripe: {stripe_h.placeholder}, GitHub: {github_h.placeholder}"
    with pytest.raises(EgressHostMismatchError):
        # Even if stripe matches, github will mismatch on api.stripe.com
        interceptor.inject_secrets(mixed, "api.stripe.com")


def test_atomic_grant_lifecycle_and_invalidation() -> None:
    manager = AtomicOperationGrantManager()

    payload_initial = {"cluster": "prod-us-east-1", "action": "scale_down", "replicas": 0}
    payload_hash = manager.compute_payload_hash(payload_initial)

    grant = manager.create_grant(
        operation_name="cluster_scale_down",
        payload_hash=payload_hash,
        ttl_seconds=60.0,
    )

    assert grant.status == GrantStatus.PENDING
    assert grant.operation_name == "cluster_scale_down"
    assert grant.payload_hash == payload_hash

    # Cannot consume unapproved pending grant
    with pytest.raises(AtomicGrantInvalidatedError):
        manager.consume_grant(grant.grant_id, "cluster_scale_down", payload_hash)

    # Approve grant
    approved = manager.approve_grant(grant.grant_id)
    assert approved.status == GrantStatus.GRANTED

    # Attempting to consume with mutated payload invalidates grant
    tampered_payload = {"cluster": "prod-us-east-1", "action": "scale_down", "replicas": 5}
    tampered_hash = manager.compute_payload_hash(tampered_payload)

    with pytest.raises(AtomicGrantInvalidatedError) as exc_info:
        manager.consume_grant(grant.grant_id, "cluster_scale_down", tampered_hash)
    assert "Payload mutation detected" in str(exc_info.value)

    # Verify status is now INVALIDATED
    updated_grant = manager.get_grant(grant.grant_id)
    assert updated_grant is not None
    assert updated_grant.status == GrantStatus.INVALIDATED


def test_atomic_grant_single_use_and_rejection() -> None:
    manager = AtomicOperationGrantManager()

    payload = {"account_id": "acc_888", "amount_cents": 50000}
    p_hash = manager.compute_payload_hash(payload)

    grant = manager.create_grant("charge_customer", p_hash)
    manager.approve_grant(grant.grant_id)

    # First consumption succeeds
    success = manager.consume_grant(grant.grant_id, "charge_customer", p_hash)
    assert success is True
    assert manager.get_grant(grant.grant_id).status == GrantStatus.USED

    # Second consumption fails (single-use enforced)
    with pytest.raises(AtomicGrantInvalidatedError) as exc_info:
        manager.consume_grant(grant.grant_id, "charge_customer", p_hash)
    assert "already been consumed" in str(exc_info.value)

    # Terminal rejection test
    grant2 = manager.create_grant("delete_user_data", p_hash)
    manager.reject_grant(grant2.grant_id, reason="Admin denied deletion")

    rejected = manager.get_grant(grant2.grant_id)
    assert rejected.status == GrantStatus.REVOKED

    # Attempting to consume revoked grant raises error
    with pytest.raises(AtomicGrantInvalidatedError) as exc_info2:
        manager.consume_grant(grant2.grant_id, "delete_user_data", p_hash)
    assert "terminally revoked and closed" in str(exc_info2.value)
