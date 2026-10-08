"""Sensitive OTP credential extraction, ephemeral redaction, and recovery link blackhole guard."""

from __future__ import annotations

import logging
import re

from myrm_agent_harness.core.security.cos_otp_isolation_jit.types import (
    BlackholeInspectionResult,
    OtpRedactionResult,
)

logger = logging.getLogger(__name__)

# Patterns matching OTP codes in context of verification messages
_OTP_PATTERN = re.compile(
    r"(?i)(?:(?:\b(?:verification\s*code|otp|passcode|one-time\s*pin|2fa\s*code|security\s*code))|验证码|动态码)"
    r"[\s:：is为是]*([0-9]{4,8}|[A-Z0-9]{6,8})(?=\b|[^0-9A-Za-z]|$)"
)

# Alternative pattern for "is 123456" in standard login SMS/Email bodies
_SMS_OTP_BODY_PATTERN = re.compile(
    r"(?i)\b(?:your\s+code\s+is|use\s+code|code\s*:|enter\s+code)\s+([0-9]{4,8})(?=\b|[^0-9A-Za-z]|$)"
)

# Password reset and account recovery URLs
_RECOVERY_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"']+(?:password[-_]?reset|reset[-_]?password|account[-_]?recovery|auth/recover|reset\?token=)[^\s<>\"']*",
    re.IGNORECASE,
)

_RECOVERY_KEYWORD_PATTERN = re.compile(
    r"(?i)(?:\b(?:password\s*reset|reset\s*your\s*password|account\s*recovery)\b|找回密码|重置密码)"
)


class SensitiveOtpRedactor:
    """Inspects messaging and email streams, redacting dynamic OTPs and enforcing recovery blackholes."""

    def redact_otps(self, text: str) -> OtpRedactionResult:
        """Dynamically identify and redact OTP credentials before LLM context injection."""
        detected_otps: list[str] = []
        sanitized = text

        def _replace_otp(match: re.Match[str]) -> str:
            full = match.group(0)
            code = match.group(1)
            detected_otps.append(code)
            return full.replace(code, "[REDACTED_SENSITIVE_CREDENTIAL:OTP]")

        sanitized = _OTP_PATTERN.sub(_replace_otp, sanitized)
        sanitized = _SMS_OTP_BODY_PATTERN.sub(_replace_otp, sanitized)

        # Check if text contains dangerous recovery links
        has_reset_link = bool(
            _RECOVERY_URL_PATTERN.search(text) or _RECOVERY_KEYWORD_PATTERN.search(text)
        )

        return OtpRedactionResult(
            original_text=text,
            sanitized_text=sanitized,
            detected_otp_codes=detected_otps,
            redaction_count=len(detected_otps),
            contains_password_reset_link=has_reset_link,
        )

    def inspect_recovery_blackhole(self, text: str) -> BlackholeInspectionResult:
        """Inspect URLs and text for password reset / account recovery links, applying absolute blackhole."""
        matched_urls = _RECOVERY_URL_PATTERN.findall(text)
        has_keywords = bool(_RECOVERY_KEYWORD_PATTERN.search(text))

        if matched_urls or has_keywords:
            return BlackholeInspectionResult(
                is_blackholed=True,
                detected_links=matched_urls,
                reason=(
                    "Account recovery or password reset credential detected. "
                    "Physical blackhole lock engaged to prevent autonomous agent account hijacking. "
                    "Human manual confirmation in external browser is required."
                ),
                human_intervention_required=True,
            )

        return BlackholeInspectionResult(
            is_blackholed=False,
            detected_links=[],
            reason="",
            human_intervention_required=False,
        )
