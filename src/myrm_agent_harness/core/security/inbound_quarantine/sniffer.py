"""Zero-trust credential sniffer detecting OTPs, reset links, and statements.

[INPUT]
- Unsanitized inbound message text from email, IM, or webhook channels.

[OUTPUT]
- Classification of detected sensitive risks and generation of safe model placeholders.

[POS]
- Pre-LLM inspection gate ensuring model prompts never receive raw credentials.
"""

from __future__ import annotations

import re

from myrm_agent_harness.core.security.inbound_quarantine.types import (
    InboundQuarantineRiskType,
)


class InboundZeroTrustSniffer:
    """Pre-model sniffer detecting inbound verification codes and credentials."""

    # 1. OTP / 2FA patterns
    _OTP_KEYWORD_PATTERN = re.compile(
        r"(?:verification\s*code|security\s*code|one-time\s*password|login\s*code|"
        r"auth(?:entication)?\s*code|confirmation\s*code|access\s*code|passcode|"
        r"otp|2fa|two-factor|验证码|动态码|校验码|授权码)",
        re.IGNORECASE,
    )
    _OTP_DIGIT_PATTERN = re.compile(
        r"(?:is|为|：|:|\s)\s*([0-9]{4,8})\b",
        re.IGNORECASE,
    )

    # 2. Password reset link patterns
    _RESET_LINK_PATTERN = re.compile(
        r"(?:https?://[^\s<>\"']+/(?:[^\s<>\"']*)?(?:reset[-_]?password|password[-_]?reset|"
        r"reset[-_]?token|auth/reset|password/new|account/recovery)[^\s<>\"']*)",
        re.IGNORECASE,
    )
    _RESET_TEXT_PATTERN = re.compile(
        r"(?:click\s*here\s*to\s*reset\s*your\s*password|重置(?:您的)?密码|找回密码)",
        re.IGNORECASE,
    )

    # 3. Financial statements & bills
    _FINANCIAL_PATTERN = re.compile(
        r"(?:bank\s*statement|credit\s*card\s*statement|account\s*statement|"
        r"monthly\s*billing\s*statement|电子对账单|银行对账单|信用卡账单|账单明细|"
        r"balance\s*due\s*:\s*[$¥€][0-9,.]+|total\s*amount\s*due\s*:\s*[$¥€][0-9,.]+)",
        re.IGNORECASE,
    )

    # 4. Raw API tokens / Secret keys
    _API_TOKEN_PATTERN = re.compile(
        r"(?:sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{36}|AKIA[0-9A-Z]{16}|"
        r"xox[baprs]-[0-9a-zA-Z]{10,}|bearer\s+[a-zA-Z0-9_\-\.]{25,})",
        re.IGNORECASE,
    )

    @classmethod
    def sniff(cls, text: str) -> list[InboundQuarantineRiskType]:
        """Sniff raw content and return list of detected risk categories."""
        if not text:
            return []

        risks: list[InboundQuarantineRiskType] = []

        # Check OTP / 2FA: Requires both OTP context and numeric or token pattern
        has_otp_keyword = bool(cls._OTP_KEYWORD_PATTERN.search(text))
        has_otp_digit = bool(cls._OTP_DIGIT_PATTERN.search(text))
        if has_otp_keyword and has_otp_digit:
            risks.append(InboundQuarantineRiskType.OTP_2FA)

        # Check Password Reset
        if cls._RESET_LINK_PATTERN.search(text) or cls._RESET_TEXT_PATTERN.search(text):
            risks.append(InboundQuarantineRiskType.PASSWORD_RESET)

        # Check Financial Statements
        if cls._FINANCIAL_PATTERN.search(text):
            risks.append(InboundQuarantineRiskType.FINANCIAL_STATEMENT)

        # Check API Tokens
        if cls._API_TOKEN_PATTERN.search(text):
            risks.append(InboundQuarantineRiskType.API_TOKEN)

        return risks

    @classmethod
    def redact_to_placeholder(
        cls,
        text: str,
        quarantine_id: str,
        risks: list[InboundQuarantineRiskType],
    ) -> str:
        """Replace sensitive raw text with a secure quarantine placeholder for the LLM."""
        risk_labels = ", ".join(r.value for r in risks)
        return (
            f"[SECURITY_QUARANTINE_TRIGGERED: Inbound message physically intercepted. "
            f"Detected sensitive risks: ({risk_labels}). Content isolated under "
            f"Quarantine ID: '{quarantine_id}'. Accessible exclusively via Human User "
            f"Release Card.]"
        )
