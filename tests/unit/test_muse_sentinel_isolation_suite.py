"""Unit tests for Muse-Style Secure VM Isolation and Sentinel Suite."""

from __future__ import annotations

import time

from myrm_agent_harness.core.security.muse_sentinel_isolation import (
    MuseSecureVmManager,
    OutboundTrafficPayload,
    SandboxIsolationTier,
    SentinelOutboundReviewer,
    SentinelVerdict,
    SingleUseCredentialProxy,
    TokenType,
)


def test_secure_vm_registration_and_lookup() -> None:
    """Verify dedicated Secure VM registration and profile lookup."""
    manager = MuseSecureVmManager()
    profile = manager.register_vm(
        user_id="user_alice",
        isolation_tier=SandboxIsolationTier.DEDICATED_SECURE_VM,
    )
    assert profile.user_id == "user_alice"
    assert profile.isolation_tier == SandboxIsolationTier.DEDICATED_SECURE_VM
    assert profile.credential_sealed is True
    assert profile.egress_mode == "sentinel_proxy"
    assert "user_alice" in profile.volume_mount

    # Lookup
    assert manager.get_vm(profile.vm_id) == profile
    assert manager.get_user_vm("user_alice") == profile
    assert manager.get_user_vm("non_existent_user") is None


def test_sentinel_secret_leakage_and_exfiltration() -> None:
    """Verify Sentinel detects raw secret leakage and exfiltration destinations."""
    reviewer = SentinelOutboundReviewer()

    # 1. Block AWS Key in header
    aws_leak = OutboundTrafficPayload(
        request_id="req_1",
        destination_url="https://api.external.com/v1/sync",
        method="POST",
        headers={"X-API-Key": "AKIAIOSFODNN7EXAMPLE"},
        body_preview="payload data",
        source_vm_id="vm_1",
    )
    res_aws = reviewer.review_outbound_traffic(aws_leak)
    assert res_aws.verdict == SentinelVerdict.BLOCK
    assert "aws_access_key" in (res_aws.matched_rule or "")
    assert res_aws.risk_score == 1.0

    # 2. Block GitHub PAT in body
    gh_leak = OutboundTrafficPayload(
        request_id="req_2",
        destination_url="https://external-service.org/report",
        method="POST",
        headers={"Content-Type": "application/json"},
        body_preview='{"secret": "ghp_1234567890abcdefghijklmnopqrstuvwxyz12"}',
        source_vm_id="vm_1",
    )
    res_gh = reviewer.review_outbound_traffic(gh_leak)
    assert res_gh.verdict == SentinelVerdict.BLOCK
    assert "github_token" in (res_gh.matched_rule or "")

    # 3. Block known exfiltration destination
    exfil = OutboundTrafficPayload(
        request_id="req_3",
        destination_url="https://pastebin.com/raw/d849h2",
        method="POST",
        headers={},
        body_preview="hello world",
        source_vm_id="vm_1",
    )
    res_exfil = reviewer.review_outbound_traffic(exfil)
    assert res_exfil.verdict == SentinelVerdict.BLOCK
    assert res_exfil.matched_rule == "blocked_exfiltration_host"

    # 4. Allow clean traffic
    clean = OutboundTrafficPayload(
        request_id="req_4",
        destination_url="https://api.github.com/repos/test/repo",
        method="GET",
        headers={"Accept": "application/json"},
        body_preview="",
        source_vm_id="vm_1",
    )
    res_clean = reviewer.review_outbound_traffic(clean)
    assert res_clean.verdict == SentinelVerdict.ALLOW
    assert res_clean.risk_score == 0.0


def test_single_use_credential_success_and_replay_block() -> None:
    """Verify single-use credential authorization and strict double-spend prevention."""
    proxy = SingleUseCredentialProxy()

    # Issue virtual payment card
    token = proxy.issue_token(
        token_type=TokenType.VIRTUAL_PAYMENT_CARD,
        max_amount=50.0,
        currency="USD",
        bound_recipient="stripe_checkout",
        ttl_seconds=300,
    )
    assert token.is_consumed is False
    assert token.virtual_token.startswith("link_vtok_virt_")

    # Redeem #1: Successful
    res1 = proxy.redeem_token(
        virtual_token=token.virtual_token,
        amount=35.0,
        currency="USD",
        recipient="stripe_checkout",
    )
    assert res1.success is True
    assert "successfully authorized" in res1.reason

    # Redeem #2: Replay attempt blocked
    res2 = proxy.redeem_token(
        virtual_token=token.virtual_token,
        amount=10.0,
        currency="USD",
        recipient="stripe_checkout",
    )
    assert res2.success is False
    assert "already been consumed" in res2.reason


def test_single_use_credential_enforcement_violations() -> None:
    """Verify budget ceiling, currency match, and bound recipient enforcements."""
    proxy = SingleUseCredentialProxy()
    token = proxy.issue_token(
        token_type=TokenType.VIRTUAL_PAYMENT_CARD,
        max_amount=20.0,
        currency="USD",
        bound_recipient="acme_store",
    )

    # 1. Over-budget violation
    over_res = proxy.redeem_token(
        virtual_token=token.virtual_token,
        amount=25.0,
        currency="USD",
        recipient="acme_store",
    )
    assert over_res.success is False
    assert "exceeds token authorization ceiling" in over_res.reason

    # 2. Currency mismatch
    curr_res = proxy.redeem_token(
        virtual_token=token.virtual_token,
        amount=15.0,
        currency="EUR",
        recipient="acme_store",
    )
    assert curr_res.success is False
    assert "Currency mismatch" in curr_res.reason

    # 3. Recipient mismatch
    recip_res = proxy.redeem_token(
        virtual_token=token.virtual_token,
        amount=15.0,
        currency="USD",
        recipient="rogue_merchant",
    )
    assert recip_res.success is False
    assert "Recipient mismatch" in recip_res.reason


def test_single_use_token_expiration_and_revocation() -> None:
    """Verify TTL expiration and administrative revocation."""
    proxy = SingleUseCredentialProxy()

    # Expired token
    exp_token = proxy.issue_token(
        token_type=TokenType.SINGLE_USE_API_KEY,
        max_amount=10.0,
        currency="USD",
        ttl_seconds=1,
    )
    time.sleep(1.1)
    res = proxy.redeem_token(
        virtual_token=exp_token.virtual_token,
        amount=5.0,
        currency="USD",
        recipient="any",
    )
    assert res.success is False
    assert "expired" in res.reason

    # Revoked token
    rev_token = proxy.issue_token(max_amount=100.0)
    assert proxy.revoke_token(rev_token.token_id) is True
    res_rev = proxy.redeem_token(
        virtual_token=rev_token.virtual_token,
        amount=5.0,
        currency="USD",
        recipient="any",
    )
    assert res_rev.success is False
    assert "already been consumed" in res_rev.reason
