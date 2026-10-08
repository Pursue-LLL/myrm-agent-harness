"""
[POS] tests/unit/test_data_sovereignty_watchdog_suite.py
[INPUT] pytest, time, myrm_agent_harness.core.security.data_sovereignty_watchdog
[OUTPUT] Unit tests for DataSovereigntyWatchdogSuite

Validates private volume data sovereignty certification, anti-annoyance value threshold gating,
and high-stakes action human consent gates.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time

from myrm_agent_harness.core.security.data_sovereignty_watchdog import (
    DataSovereigntyWatchdogSuite,
    HighStakesActionType,
    ProactivityValueLevel,
    SovereigntySealLevel,
)


def test_sovereignty_seal_issuance_and_verification() -> None:
    """Validate data sovereignty sealing and cryptographic verification for private volumes."""
    suite = DataSovereigntyWatchdogSuite()

    # 1. Issue seal
    seal = suite.issue_sovereignty_seal(
        storage_target="sqlite:///user_data/private/ledger.db",
        volume_mount_path="/var/lib/myrm/user_volume_42",
        seal_level=SovereigntySealLevel.PRIVATE_SANDBOX_VOLUME,
    )
    assert seal.seal_id.startswith("seal-")
    assert seal.central_cloud_zero_retention is True
    assert len(seal.checksum) == 64

    # 2. Verify seal
    assert suite.verify_sovereignty_seal(seal.seal_id) is True
    assert suite.verify_sovereignty_seal("seal-non-existent") is False

    # 3. Latest seal
    latest = suite.get_latest_seal()
    assert latest is not None
    assert latest.seal_id == seal.seal_id


def test_sub_intrusive_watchdog_filtering_and_throttling() -> None:
    """Validate anti-annoyance value threshold gating and service-level throttling."""
    suite = DataSovereigntyWatchdogSuite(min_savings_cents=1000)
    now = time.time()

    # 1. Trivial noise suggestion (savings $2.50 < $10.00 and no deadline)
    card_noise = suite.evaluate_proactive_suggestion(
        title="Minor storage cleanup",
        service_name="CloudStorage",
        potential_savings_cents=250,
        deadline_epoch=None,
        message="You could save $2.50 by deleting old logs.",
    )
    assert card_noise.value_level == ProactivityValueLevel.MODERATE_SUGGESTION
    assert card_noise.is_suppressed is True

    # 2. High value suggestion (savings $25.00 >= $10.00)
    card_high = suite.evaluate_proactive_suggestion(
        title="Unused Cloud compute instance",
        service_name="AWSCompute",
        potential_savings_cents=2500,
        deadline_epoch=None,
        message="Terminating unused EC2 instance will save $25.00/month.",
    )
    assert card_high.value_level == ProactivityValueLevel.HIGH_VALUE_ALERT
    assert card_high.is_suppressed is False

    # 3. Critical deadline (trial ends in 24 hours)
    card_deadline = suite.evaluate_proactive_suggestion(
        title="Trial expiration alert",
        service_name="VideoTool",
        potential_savings_cents=500,
        deadline_epoch=now + 86400.0,  # 24h
        message="Free trial ends in 24 hours. Cancel to avoid charges.",
    )
    assert card_deadline.value_level == ProactivityValueLevel.CRITICAL_DEADLINE
    assert card_deadline.is_suppressed is False

    # 4. Immediate duplicate alert for same service is throttled
    card_duplicate = suite.evaluate_proactive_suggestion(
        title="Another instance found",
        service_name="AWSCompute",
        potential_savings_cents=3000,
        deadline_epoch=None,
        message="Another instance saving found.",
    )
    assert card_duplicate.is_suppressed is True

    # 5. Check active list
    active_cards = suite.list_active_notification_cards()
    assert len(active_cards) == 2
    assert any(c.card_id == card_high.card_id for c in active_cards)
    assert any(c.card_id == card_deadline.card_id for c in active_cards)


def test_high_stakes_consent_gate_lifecycle() -> None:
    """Validate mandatory human consent ticketing for irreversible financial mutations."""
    suite = DataSovereigntyWatchdogSuite()

    # 1. Create subscription cancellation ticket
    ticket = suite.create_high_stakes_consent(
        action_type=HighStakesActionType.SUBSCRIPTION_CANCEL,
        service_name="Adobe Creative Cloud",
        financial_impact_cents=5999,
        payload_summary="Automated cancellation of $59.99/mo subscription",
    )
    assert ticket.ticket_id.startswith("ticket-")
    assert ticket.is_approved is False
    assert ticket.is_denied is False

    pending = suite.list_pending_consents()
    assert len(pending) == 1
    assert pending[0].ticket_id == ticket.ticket_id

    # 2. Approve ticket
    approved = suite.approve_consent(ticket.ticket_id)
    assert approved.is_approved is True
    assert approved.is_denied is False
    assert len(suite.list_pending_consents()) == 0

    # 3. Create and deny dispute ticket
    ticket_disp = suite.create_high_stakes_consent(
        action_type=HighStakesActionType.REFUND_DISPUTE,
        service_name="Unknown Merchant",
        financial_impact_cents=12000,
        payload_summary="Submit bank chargeback dispute",
    )
    denied = suite.deny_consent(ticket_disp.ticket_id)
    assert denied.is_approved is False
    assert denied.is_denied is True


def test_metrics_tracking() -> None:
    """Validate cumulative operational metrics."""
    suite = DataSovereigntyWatchdogSuite()

    suite.issue_sovereignty_seal("db://local", "/vol")
    suite.evaluate_proactive_suggestion("test", "svc", 100, None, "msg")
    t = suite.create_high_stakes_consent(
        HighStakesActionType.BALANCE_TRANSFER, "bank", 500, "transfer"
    )
    suite.approve_consent(t.ticket_id)

    m = suite.metrics
    assert m.sovereignty_seals_issued_total == 1
    assert m.proactive_scans_total == 1
    assert m.noise_suppressed_total == 1
    assert m.high_stakes_actions_blocked_total == 1
    assert m.high_stakes_consents_approved_total == 1
