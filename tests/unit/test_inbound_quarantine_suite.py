"""Unit tests for Inbound Zero-Trust Quarantine & Redaction Suite in myrm-agent-harness."""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.core.security.inbound_quarantine import (
    InboundQuarantineGate,
    InboundQuarantineRiskType,
    InboundQuarantineStatus,
    InboundQuarantineVault,
    InboundZeroTrustSniffer,
)


@pytest.fixture
def gate() -> InboundQuarantineGate:
    return InboundQuarantineGate()


def test_sniffer_detects_otp_and_2fa() -> None:
    en_msg = "Hello, your login verification code is 492018. It will expire in 5 minutes."
    risks_en = InboundZeroTrustSniffer.sniff(en_msg)
    assert InboundQuarantineRiskType.OTP_2FA in risks_en

    zh_msg = "【安全中心】您正在绑定设备，动态码为：981203，切勿告知他人。"
    risks_zh = InboundZeroTrustSniffer.sniff(zh_msg)
    assert InboundQuarantineRiskType.OTP_2FA in risks_zh


def test_sniffer_detects_password_reset() -> None:
    msg = "Someone requested to reset your password. Click here: https://id.corp.com/auth/reset-password?token=sec_9812739"
    risks = InboundZeroTrustSniffer.sniff(msg)
    assert InboundQuarantineRiskType.PASSWORD_RESET in risks


def test_sniffer_detects_financial_statement() -> None:
    msg = "Your monthly credit card statement is now available. Balance due: $3,250.00."
    risks = InboundZeroTrustSniffer.sniff(msg)
    assert InboundQuarantineRiskType.FINANCIAL_STATEMENT in risks


def test_sniffer_detects_api_tokens() -> None:
    msg = "Use token sk-1234567890abcdefghijklmnopqrstuvwxyz to authenticate."
    risks = InboundZeroTrustSniffer.sniff(msg)
    assert InboundQuarantineRiskType.API_TOKEN in risks


def test_gate_clean_message_passthrough(gate: InboundQuarantineGate) -> None:
    clean_msg = "Hi team, let's meet at 3pm to review the quarterly roadmap presentation."
    res = gate.inspect_and_quarantine(
        content=clean_msg,
        channel_type="email",
        sender="alice@corp.com",
        recipient="agent@corp.com",
    )
    assert res.is_quarantined is False
    assert len(res.detected_risks) == 0
    assert res.safe_content == clean_msg
    assert res.quarantine_id is None


def test_gate_quarantines_sensitive_content_and_releases(
    gate: InboundQuarantineGate,
) -> None:
    sensitive_msg = (
        "Security Alert: Your one-time password is 654321. "
        "Do not share this OTP with anyone."
    )
    res = gate.inspect_and_quarantine(
        content=sensitive_msg,
        channel_type="email",
        sender="auth-service@bank.com",
        recipient="user@corp.com",
    )

    # 1. Verify physical interception & redaction
    assert res.is_quarantined is True
    assert InboundQuarantineRiskType.OTP_2FA in res.detected_risks
    assert "654321" not in res.safe_content
    assert "[SECURITY_QUARANTINE_TRIGGERED" in res.safe_content
    assert res.quarantine_id is not None
    assert "/release" in str(res.release_card_url)

    # 2. Verify metadata
    record = gate.get_quarantine_record(res.quarantine_id)
    assert record is not None
    assert record.status == InboundQuarantineStatus.ACTIVE
    assert record.sender == "auth-service@bank.com"

    # 3. Authorized human release
    released = gate.release_quarantine(res.quarantine_id)
    assert released is not None
    assert released.quarantine_id == res.quarantine_id
    assert released.original_content == sensitive_msg
    assert "654321" in released.original_content

    # Status should transition to RELEASED
    updated_rec = gate.get_quarantine_record(res.quarantine_id)
    assert updated_rec is not None
    assert updated_rec.status == InboundQuarantineStatus.RELEASED


def test_vault_ttl_expiration_and_purge() -> None:
    vault = InboundQuarantineVault()
    # Store with 0.05 second TTL
    rec = vault.store(
        channel_type="im",
        sender="bot@test.com",
        recipient="user@test.com",
        original_content="Secret OTP is 112233",
        risks=[InboundQuarantineRiskType.OTP_2FA],
        ttl_seconds=0.05,
    )
    qid = rec.quarantine_id
    assert vault.get_record(qid) is not None

    time.sleep(0.08)

    # After expiration, release must be denied
    released = vault.release_payload(qid)
    assert released is None

    # Purge should eliminate the expired record
    purged_count = vault.purge_expired()
    assert purged_count >= 1
    assert vault.get_record(qid) is None
