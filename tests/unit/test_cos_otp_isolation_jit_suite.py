"""Unit tests for CoS Sensitive OTP Dynamic Isolation, Recovery Blackhole, and JIT Authorization Suite."""

from __future__ import annotations

import time

from myrm_agent_harness.core.security.cos_otp_isolation_jit.jit_gate import (
    IntentBoundJitAuthorizationGate,
)
from myrm_agent_harness.core.security.cos_otp_isolation_jit.otp_redactor import (
    SensitiveOtpRedactor,
)
from myrm_agent_harness.core.security.cos_otp_isolation_jit.quota_rails import (
    QuotaWatermarkGuard,
)
from myrm_agent_harness.core.security.cos_otp_isolation_jit.types import (
    QuotaWatermarkTier,
)


def test_otp_redaction_english_and_chinese() -> None:
    redactor = SensitiveOtpRedactor()

    # 1. English verification message
    en_msg = "Security alert: Your verification code is 849201 for banking portal."
    en_res = redactor.redact_otps(en_msg)
    assert en_res.redaction_count == 1
    assert "849201" in en_res.detected_otp_codes
    assert "849201" not in en_res.sanitized_text
    assert "[REDACTED_SENSITIVE_CREDENTIAL:OTP]" in en_res.sanitized_text

    # 2. Chinese SMS message
    zh_msg = "【服务中心】您的登录动态码为 678912，有效期5分钟，请勿泄露给他人。"
    zh_res = redactor.redact_otps(zh_msg)
    assert zh_res.redaction_count == 1
    assert "678912" in zh_res.detected_otp_codes
    assert "678912" not in zh_res.sanitized_text
    assert "[REDACTED_SENSITIVE_CREDENTIAL:OTP]" in zh_res.sanitized_text

    # 3. Benign message with normal numbers
    benign = "Total order price is $120.45 across 3 items."
    benign_res = redactor.redact_otps(benign)
    assert benign_res.redaction_count == 0
    assert benign_res.sanitized_text == benign


def test_password_reset_blackhole_inspection() -> None:
    redactor = SensitiveOtpRedactor()

    # 1. Dangerous password reset URL
    url_msg = "Click here to reset your credentials: https://auth.provider.com/password-reset?token=xyz123"
    url_res = redactor.inspect_recovery_blackhole(url_msg)
    assert url_res.is_blackholed is True
    assert url_res.human_intervention_required is True
    assert len(url_res.detected_links) >= 1
    assert "blackhole lock engaged" in url_res.reason

    # 2. Chinese reset keyword
    zh_msg = "用户请求重置密码，请核验身份。"
    zh_res = redactor.inspect_recovery_blackhole(zh_msg)
    assert zh_res.is_blackholed is True
    assert zh_res.human_intervention_required is True

    # 3. Benign shopping link
    benign_msg = "Check out our sale at https://shop.com/products/deals"
    benign_res = redactor.inspect_recovery_blackhole(benign_msg)
    assert benign_res.is_blackholed is False
    assert benign_res.human_intervention_required is False


def test_jit_authorization_gate_burn_after_reading_lifecycle() -> None:
    gate = IntentBoundJitAuthorizationGate()
    session_id = "session-checkout-42"
    target_domain = "checkout.merchant.com"
    otp = "998811"

    ticket = gate.issue_ticket(
        session_id=session_id,
        target_domain=target_domain,
        purpose="Checkout payment verification",
        otp_code=otp,
        validity_seconds=120,
    )

    assert ticket.session_id == session_id
    assert ticket.consumed is False

    # 1. Domain mismatch consumption fails
    bad_domain_res = gate.consume_ticket(ticket.ticket_id, target_domain="attacker.com")
    assert bad_domain_res is None

    # 2. Legitimate domain consumption succeeds
    valid_res = gate.consume_ticket(ticket.ticket_id, target_domain=target_domain)
    assert valid_res == otp

    # 3. Second consumption fails (burn-after-reading single use)
    second_res = gate.consume_ticket(ticket.ticket_id, target_domain=target_domain)
    assert second_res is None


def test_jit_authorization_gate_expired_ticket_rejected() -> None:
    gate = IntentBoundJitAuthorizationGate()
    ticket = gate.issue_ticket(
        session_id="s1",
        target_domain="auth.com",
        purpose="Login",
        otp_code="123456",
        validity_seconds=-5,  # already expired
    )
    time.sleep(0.01)
    res = gate.consume_ticket(ticket.ticket_id, target_domain="auth.com")
    assert res is None


def test_quota_watermark_evaluation_tiers() -> None:
    # 1. Under 50%
    q_norm = QuotaWatermarkGuard.assess_quota(used_units=30, max_units=100)
    assert q_norm.tier == QuotaWatermarkTier.NORMAL_UNDER_50
    assert q_norm.alert_message is None
    assert q_norm.fallback_model_recommended is None

    # 2. 50% Watermark
    q_50 = QuotaWatermarkGuard.assess_quota(used_units=55, max_units=100)
    assert q_50.tier == QuotaWatermarkTier.WARNING_50_PERCENT
    assert "50%" in (q_50.alert_message or "")

    # 3. 75% Watermark
    q_75 = QuotaWatermarkGuard.assess_quota(used_units=76, max_units=100)
    assert q_75.tier == QuotaWatermarkTier.ELEVATED_75_PERCENT
    assert "75%" in (q_75.alert_message or "")
    assert q_75.fallback_model_recommended is not None

    # 4. 90% Watermark
    q_90 = QuotaWatermarkGuard.assess_quota(used_units=92, max_units=100)
    assert q_90.tier == QuotaWatermarkTier.CRITICAL_90_PERCENT
    assert "90%" in (q_90.alert_message or "")

    # 5. 100% Watermark
    q_100 = QuotaWatermarkGuard.assess_quota(used_units=105, max_units=100)
    assert q_100.tier == QuotaWatermarkTier.EXHAUSTED_100_PERCENT
    assert "100%" in (q_100.alert_message or "")
