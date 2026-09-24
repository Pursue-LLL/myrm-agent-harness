# INPUT: SpendGovernor, SpendGovernorConfig, SpendLease, is_spend_voucher
# OUTPUT: Test cases for SpendGovernor micro-spending limits, leases, allowlists, and vouchers
# POS: Harness core security tests. Verifies autonomous commerce spending safety primitives.

from __future__ import annotations

from myrm_agent_harness.core.security.egress.spend_governor import (
    SPEND_VOUCHER_PREFIX,
    SPEND_VOUCHER_SUFFIX,
    SpendGovernor,
    SpendGovernorConfig,
    is_spend_voucher,
)


def test_spend_governor_basic_reserve_and_commit() -> None:
    """Test standard reserve -> voucher issuance -> commit flow."""
    governor = SpendGovernor(
        SpendGovernorConfig(
            daily_cap_cents=1000,
            per_action_cap_cents=200,
            allowed_merchants=("namesilo.com",),
        )
    )

    res = governor.reserve(merchant_domain="namesilo.com", amount_cents=99)
    assert res.success is True
    assert res.code == "APPROVED"
    assert res.lease is not None
    assert res.voucher is not None
    assert res.lease.amount_cents == 99
    assert res.lease.status == "reserved"
    assert is_spend_voucher(res.voucher) is True

    # Verify voucher payload
    data = governor.verify_spend_voucher(res.voucher)
    assert data is not None
    assert data["amt"] == 99
    assert data["dom"] == "namesilo.com"
    assert data["lid"] == res.lease.lease_id

    # Commit the lease
    commit_res = governor.commit(res.lease.lease_id, idempotency_key="txn_123")
    assert commit_res.success is True
    assert commit_res.code == "COMMITTED"
    assert commit_res.entry_hash is not None
    assert commit_res.action_digest is not None

    # Check metrics
    metrics = governor.get_metrics()
    assert metrics["dailySpentCents"] == 99
    assert metrics["remainingCents"] == 901
    assert metrics["activeReservedCents"] == 0


def test_merchant_whitelist_and_wildcard() -> None:
    """Test strict domain and wildcard glob allowlist enforcement."""
    governor = SpendGovernor(
        SpendGovernorConfig(
            allowed_merchants=("*.openai.com", "namesilo.com", "2captcha.com"),
        )
    )

    assert governor.is_merchant_allowed("api.openai.com") is True
    assert governor.is_merchant_allowed("chat.openai.com") is True
    assert governor.is_merchant_allowed("namesilo.com") is True
    assert governor.is_merchant_allowed("2captcha.com") is True
    assert governor.is_merchant_allowed("malicious-store.com") is False
    assert governor.is_merchant_allowed("openai.com.evil.com") is False

    # Untrusted merchant rejection
    res = governor.reserve("evil.com", 50)
    assert res.success is False
    assert res.code == "UNTRUSTED_MERCHANT"
    assert "not in allowed merchants" in res.message


def test_invalid_amount_protection() -> None:
    """Test protection against negative, zero, and non-integer spending amounts."""
    governor = SpendGovernor()

    # Negative amount (fund draining attempt)
    res_neg = governor.reserve("namesilo.com", -100)
    assert res_neg.success is False
    assert res_neg.code == "INVALID_AMOUNT"

    # Zero amount
    res_zero = governor.reserve("namesilo.com", 0)
    assert res_zero.success is False
    assert res_zero.code == "INVALID_AMOUNT"


def test_per_action_cap_exceeded() -> None:
    """Test that requests exceeding the per-action cap are strictly denied."""
    governor = SpendGovernor(
        SpendGovernorConfig(
            per_action_cap_cents=200,  # $2.00 cap
            daily_cap_cents=1000,
        )
    )

    res = governor.reserve("namesilo.com", 250)
    assert res.success is False
    assert res.code == "LIMIT_EXCEEDED"
    assert "exceeds per-action cap" in res.message


def test_daily_cap_and_concurrent_reservation_exhaustion() -> None:
    """Test that concurrent reservations accumulate and block overflow."""
    governor = SpendGovernor(
        SpendGovernorConfig(
            daily_cap_cents=500,
            per_action_cap_cents=200,
        )
    )

    # Reserve 200 cents (1st)
    r1 = governor.reserve("namesilo.com", 200)
    assert r1.success is True

    # Reserve 200 cents (2nd)
    r2 = governor.reserve("namesilo.com", 200)
    assert r2.success is True

    # Attempt to reserve 150 cents (200 + 200 + 150 = 550 > 500)
    r3 = governor.reserve("namesilo.com", 150)
    assert r3.success is False
    assert r3.code == "LIMIT_EXCEEDED"

    # Can still reserve 100 cents (200 + 200 + 100 = 500 == cap)
    r4 = governor.reserve("namesilo.com", 100)
    assert r4.success is True


def test_lease_release() -> None:
    """Test releasing a reserved lease frees up budget immediately."""
    governor = SpendGovernor(
        SpendGovernorConfig(
            daily_cap_cents=300,
            per_action_cap_cents=200,
        )
    )

    r1 = governor.reserve("namesilo.com", 200)
    assert r1.success is True
    assert governor.get_active_reserved_cents() == 200

    # Release lease 1
    assert r1.lease is not None
    released = governor.release(r1.lease.lease_id)
    assert released is True
    assert governor.get_active_reserved_cents() == 0

    # Can now reserve up to full daily cap again
    r2 = governor.reserve("namesilo.com", 200)
    assert r2.success is True


def test_lease_expiration_and_cleanup() -> None:
    """Test auto-expiration of stale uncommitted leases."""
    governor = SpendGovernor(
        SpendGovernorConfig(
            daily_cap_cents=300,
            per_action_cap_cents=200,
            lease_ttl_seconds=1,
        )
    )

    t0 = 1000.0
    r1 = governor.reserve("namesilo.com", 200, now=t0)
    assert r1.success is True
    assert r1.lease is not None
    assert r1.lease.expires_at == 1001.0

    # Advance time past expiration
    t1 = 1002.0
    expired = governor.cleanup_expired_leases(now=t1)
    assert expired == 1
    assert r1.lease.status == "expired"
    assert governor.get_active_reserved_cents(now=t1) == 0

    # Attempting to commit an expired lease fails cleanly
    commit_res = governor.commit(r1.lease.lease_id, now=t1)
    assert commit_res.success is False
    assert commit_res.code == "LEASE_EXPIRED"


def test_emergency_freeze_and_unfreeze() -> None:
    """Test one-click emergency killswitch immediately blocks any reservation."""
    governor = SpendGovernor(
        SpendGovernorConfig(
            daily_cap_cents=1000,
            per_action_cap_cents=200,
            is_frozen=False,
        )
    )

    # Freeze
    governor.freeze()
    res = governor.reserve("namesilo.com", 50)
    assert res.success is False
    assert res.code == "FROZEN"
    assert governor.config.is_frozen is True

    # Unfreeze
    governor.unfreeze()
    res2 = governor.reserve("namesilo.com", 50)
    assert res2.success is True
    assert res2.code == "APPROVED"


def test_forged_spend_voucher_rejected() -> None:
    """Test that forged or tampered vouchers are rejected by signature check."""
    governor = SpendGovernor()
    assert governor.verify_spend_voucher("invalid-voucher") is None
    assert governor.verify_spend_voucher(f"{SPEND_VOUCHER_PREFIX}forged{SPEND_VOUCHER_SUFFIX}") is None


def test_utc_calendar_day_rolling_and_restore_state() -> None:
    """Test UTC calendar day boundary rolling and persistent state restoration."""
    t0 = 86300.0  # Day 0 (86300 // 86400 == 0)
    governor = SpendGovernor(
        SpendGovernorConfig(daily_cap_cents=1000, per_action_cap_cents=500),
    )
    # Manually set day 0 index for deterministic testing
    governor._current_day_index = 0

    # Restore state on day 0
    governor.restore_daily_spent(spent_cents=450, now=t0)
    assert governor.get_metrics(now=t0)["dailySpentCents"] == 450
    assert governor.get_metrics(now=t0)["remainingCents"] == 550

    # Cross UTC day boundary (86500 // 86400 == 1)
    t1 = 86500.0
    metrics_next_day = governor.get_metrics(now=t1)
    assert metrics_next_day["dailySpentCents"] == 0
    assert metrics_next_day["remainingCents"] == 1000


def test_terminal_lease_pruning_and_eviction() -> None:
    """Test that terminal leases older than retention window are evicted from memory."""
    t0 = 1000.0
    governor = SpendGovernor(
        SpendGovernorConfig(lease_ttl_seconds=60),
    )
    r1 = governor.reserve("namesilo.com", 100, now=t0)
    assert r1.success is True
    assert r1.lease is not None
    lid = r1.lease.lease_id

    # Commit lease at t0 + 10
    commit_res = governor.commit(lid, now=t0 + 10)
    assert commit_res.success is True

    # At t0 + 200, lease is terminal (committed), but within 3600s retention
    governor.cleanup_expired_leases(now=t0 + 200)
    assert lid in governor._leases

    # At t0 + 4000 (> 60 + 3600), lease should be evicted from memory
    governor.cleanup_expired_leases(now=t0 + 4000)
    assert lid not in governor._leases
