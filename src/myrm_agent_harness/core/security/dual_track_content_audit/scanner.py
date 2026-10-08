import re
from typing import ClassVar

from .types import AuditVerdict, ContentRiskLevelEnum, ViolationCategoryEnum


class OutBandContentScanner:
    """Out-of-band deep content inspection engine scanning for leaks, policy violations, and threats."""

    _PATTERN_RULES: ClassVar[list[tuple[ViolationCategoryEnum, ContentRiskLevelEnum, re.Pattern[str], str]]] = [
        # Credential leak patterns
        (
            ViolationCategoryEnum.CREDENTIAL_LEAK,
            ContentRiskLevelEnum.CRITICAL,
            re.compile(r"-----BEGIN\s+(?:RSA|EC|DSA|OPENSSH|PGP)?\s*PRIVATE\s+KEY-----", re.IGNORECASE),
            "Private cryptographic key material detected in stream output.",
        ),
        (
            ViolationCategoryEnum.CREDENTIAL_LEAK,
            ContentRiskLevelEnum.CRITICAL,
            re.compile(r"(?:ghp_[a-zA-Z0-9]{36}|gho_[a-zA-Z0-9]{36}|glpat-[a-zA-Z0-9\-]{20,})"),
            "Personal access token or OAuth secret detected.",
        ),
        (
            ViolationCategoryEnum.CREDENTIAL_LEAK,
            ContentRiskLevelEnum.CRITICAL,
            re.compile(r"(?:sk-[a-zA-Z0-9]{32,}|AKIA[0-9A-Z]{16})"),
            "API key or cloud provider secret credential detected.",
        ),
        # Financial confidentiality
        (
            ViolationCategoryEnum.FINANCIAL_CONFIDENTIAL,
            ContentRiskLevelEnum.CRITICAL,
            re.compile(r"(?:未公开财报|内部Q[1-4]净利润|并购重组内幕底价|未披露财务报表|非公开股权转让底价)"),
            "Undisclosed corporate financial data or material non-public information.",
        ),
        # Trade secrets
        (
            ViolationCategoryEnum.TRADE_SECRET,
            ContentRiskLevelEnum.CRITICAL,
            re.compile(r"(?:商业绝密|核心算法未公开源码|绝密客户底价清单|国家秘密\(绝密\))"),
            "Protected trade secrets or restricted intellectual property detected.",
        ),
        # Prompt injection & jailbreak
        (
            ViolationCategoryEnum.PROMPT_INJECTION,
            ContentRiskLevelEnum.CRITICAL,
            re.compile(r"(?:ignore all previous instructions and|bypass corporate security policy|developer mode enabled: unlock full access)", re.IGNORECASE),
            "Adversarial prompt injection or security policy override phrase detected.",
        ),
        # Political sensitivity
        (
            ViolationCategoryEnum.POLITICAL_SENSITIVE,
            ContentRiskLevelEnum.CRITICAL,
            re.compile(r"(?:颠覆国家政权|分裂国家统一宣传|推翻宪法基本制度)"),
            "Severe political sensitive violation detected.",
        ),
    ]

    def scan_text(self, text: str) -> AuditVerdict:
        """Scan text buffer against deep out-of-band compliance rules."""
        if not text or not text.strip():
            return AuditVerdict(
                is_violation=False,
                risk_level=ContentRiskLevelEnum.SAFE,
                category=ViolationCategoryEnum.NONE,
                confidence=1.0,
                matched_pattern=None,
                reason="Empty or whitespace text buffer.",
            )

        for category, risk_level, pattern, reason in self._PATTERN_RULES:
            match = pattern.search(text)
            if match is not None:
                matched_snippet = match.group(0)[:60]
                return AuditVerdict(
                    is_violation=True,
                    risk_level=risk_level,
                    category=category,
                    confidence=0.98,
                    matched_pattern=matched_snippet,
                    reason=reason,
                )

        return AuditVerdict(
            is_violation=False,
            risk_level=ContentRiskLevelEnum.SAFE,
            category=ViolationCategoryEnum.NONE,
            confidence=1.0,
            matched_pattern=None,
            reason="Content complies with security and confidentiality policies.",
        )
