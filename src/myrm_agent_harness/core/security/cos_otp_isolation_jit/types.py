"""Type definitions for CoS Sensitive OTP Dynamic Isolation, Recovery Blackhole, and JIT Authorization Suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class QuotaWatermarkTier(StrEnum):
    """Progressive quota usage watermark tiers."""

    NORMAL_UNDER_50 = "NORMAL_UNDER_50"  # Usage < 50%
    WARNING_50_PERCENT = "WARNING_50_PERCENT"  # 50% <= Usage < 75%
    ELEVATED_75_PERCENT = "ELEVATED_75_PERCENT"  # 75% <= Usage < 90%
    CRITICAL_90_PERCENT = "CRITICAL_90_PERCENT"  # 90% <= Usage < 100%
    EXHAUSTED_100_PERCENT = "EXHAUSTED_100_PERCENT"  # Usage >= 100%


@dataclass(slots=True, frozen=True)
class OtpRedactionResult:
    """Result of message inspection and OTP ephemeral redaction."""

    original_text: str
    sanitized_text: str
    detected_otp_codes: list[str] = field(default_factory=list)
    redaction_count: int = 0
    contains_password_reset_link: bool = False


@dataclass(slots=True, frozen=True)
class BlackholeInspectionResult:
    """Result of password reset URL and recovery email blackhole inspection."""

    is_blackholed: bool
    detected_links: list[str] = field(default_factory=list)
    reason: str = ""
    human_intervention_required: bool = False


@dataclass(slots=True, frozen=True)
class JitOtpTicket:
    """Time-bound ephemeral authorization ticket bound to confirmed user checkout/login intent."""

    ticket_id: str
    session_id: str
    target_domain: str
    purpose: str
    otp_code: str
    issued_at: float
    expires_at: float
    consumed: bool = False


@dataclass(slots=True, frozen=True)
class QuotaAssessment:
    """Quota usage calculation with watermark alerts and fallback recommendations."""

    used_units: float
    max_units: float
    usage_ratio: float
    tier: QuotaWatermarkTier
    alert_message: str | None = None
    fallback_model_recommended: str | None = None
