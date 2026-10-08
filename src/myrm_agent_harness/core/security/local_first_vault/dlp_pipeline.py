"""Transparent In-situ DLP Sensitive Data Redaction Pipeline."""

from __future__ import annotations

import re

from .types import (
    DlpRedactionMatch,
    DlpRedactionResult,
    DlpSensitivityCategory,
)

_INTERNAL_IP_PATTERN = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b"
)
_INTERNAL_DOMAIN_PATTERN = re.compile(
    r"\b[a-zA-Z0-9_\-\.]+\.(?:internal|corp|local|lan|intra)\b", re.IGNORECASE
)
_SECRET_TOKEN_PATTERN = re.compile(
    r"\b(?:sk_live_[0-9a-zA-Z]{24,}|ghp_[0-9a-zA-Z_]{36,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_\-]{30,})\b"
)
_PHONE_PATTERN = re.compile(
    r"\b(?:\+?86[- ]?)?1[3-9]\d{9}\b|\b\d{3}[-.]\d{3}[-.]\d{4}\b"
)
_PRICE_PATTERN = re.compile(
    r"(?:\$|¥|￥|USD\s+|RMB\s+)\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})?", re.IGNORECASE
)


class TransparentDlpRedactionPipeline:
    """Scans and masks internal IPs, intranet domains, credentials, and confidential pricing in-situ."""

    def sanitize_content(
        self,
        content: str,
        enable_price_redaction: bool = True,
    ) -> DlpRedactionResult:
        """Execute comprehensive DLP inspection and return sanitized output with audit matches."""
        current_text = content
        matches: list[DlpRedactionMatch] = []
        categories_found: set[DlpSensitivityCategory] = set()

        rules: list[tuple[DlpSensitivityCategory, re.Pattern[str], str]] = [
            (DlpSensitivityCategory.INTERNAL_IP, _INTERNAL_IP_PATTERN, "[INTERNAL_IP_MASKED]"),
            (DlpSensitivityCategory.INTERNAL_DOMAIN, _INTERNAL_DOMAIN_PATTERN, "[INTERNAL_DOMAIN_MASKED]"),
            (DlpSensitivityCategory.SECRET_TOKEN, _SECRET_TOKEN_PATTERN, "[SECRET_TOKEN_REDACTED]"),
            (DlpSensitivityCategory.PHONE_NUMBER, _PHONE_PATTERN, "[PHONE_REDACTED]"),
        ]

        if enable_price_redaction:
            rules.append(
                (DlpSensitivityCategory.COMMERCIAL_PRICE, _PRICE_PATTERN, "[CONFIDENTIAL_PRICE_REDACTED]")
            )

        for category, pattern, replacement in rules:
            for m in pattern.finditer(current_text):
                matched_snippet = m.group(0)
                matches.append(
                    DlpRedactionMatch(
                        category=category,
                        original_snippet=matched_snippet,
                        redacted_snippet=replacement,
                        start=m.start(),
                        end=m.end(),
                    )
                )
                categories_found.add(category)

            current_text = pattern.sub(replacement, current_text)

        return DlpRedactionResult(
            original_length=len(content),
            redacted_length=len(current_text),
            total_redactions=len(matches),
            categories_found=sorted(categories_found, key=lambda c: c.value),
            matches=matches,
            sanitized_content=current_text,
        )
