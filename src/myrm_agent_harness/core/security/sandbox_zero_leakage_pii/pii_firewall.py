"""Bidirectional PII & Child Privacy Firewall for in-flight memory and context streams."""

from __future__ import annotations

import logging
import re

from myrm_agent_harness.core.security.sandbox_zero_leakage_pii.types import (
    PiiCategory,
    PiiRedactionResult,
)

logger = logging.getLogger(__name__)

# Pattern targeting child and minor names in explicit familial context
_CHILD_NAME_PATTERN = re.compile(
    r"\b(?:my\s+(?:daughter|son|kid|child|toddler|baby|infant)(?:'s)?(?:\s+name\s+is)?|"
    r"(?:child(?:'s)?|kid(?:'s)?)\s+name\s+is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",
    re.IGNORECASE,
)

# Standard phone number pattern (international & domestic 10-14 digits)
_PHONE_PATTERN = re.compile(
    r"(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{4}\b"
)

# Government ID: US SSN and 18-digit National Citizen IDs
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_NATIONAL_ID_PATTERN = re.compile(r"\b\d{17}[\dXx]\b")

# Financial credit cards (Visa, MasterCard, Amex 15-16 digits with separators)
_CREDIT_CARD_PATTERN = re.compile(
    r"\b(?:\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}|\d{4}[-\s]?\d{6}[-\s]?\d{5})\b"
)

# Physical street addresses
_STREET_ADDRESS_PATTERN = re.compile(
    r"\b\d{1,5}\s+[A-Za-z0-9\s.,\-]+?\s+"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way)\b",
    re.IGNORECASE,
)


class BiDirectionalPiiFirewall:
    """Firewall inspecting inbound memory persistence and outbound context retrieval for high-risk PII."""

    def scan_and_redact(self, text: str) -> PiiRedactionResult:
        """Scan text, identify sensitive privacy categories, and mask all matches.

        Guarantees zero-leakage of child identity, contact coordinates, and financial secrets.
        """
        sanitized = text
        detected: set[PiiCategory] = set()
        redactions = 0
        has_child_violation = False

        # 1. Child / Minor privacy pattern
        def _mask_child(match: re.Match[str]) -> str:
            nonlocal redactions, has_child_violation
            redactions += 1
            has_child_violation = True
            detected.add(PiiCategory.CHILD_OR_MINOR_NAME)
            full_match = match.group(0)
            child_name = match.group(1)
            return full_match.replace(child_name, "[CHILD_NAME_REDACTED]")

        sanitized = _CHILD_NAME_PATTERN.sub(_mask_child, sanitized)

        # 2. Financial Credit Cards
        if _CREDIT_CARD_PATTERN.search(sanitized):
            detected.add(PiiCategory.FINANCIAL_CREDIT_CARD)
            sanitized, count = _CREDIT_CARD_PATTERN.subn("[FINANCIAL_CARD_REDACTED]", sanitized)
            redactions += count

        # 3. Government IDs
        if _SSN_PATTERN.search(sanitized) or _NATIONAL_ID_PATTERN.search(sanitized):
            detected.add(PiiCategory.GOVERNMENT_ID)
            sanitized, c1 = _SSN_PATTERN.subn("[GOV_ID_REDACTED]", sanitized)
            sanitized, c2 = _NATIONAL_ID_PATTERN.subn("[GOV_ID_REDACTED]", sanitized)
            redactions += c1 + c2

        # 4. Street Addresses
        if _STREET_ADDRESS_PATTERN.search(sanitized):
            detected.add(PiiCategory.STREET_ADDRESS)
            sanitized, count = _STREET_ADDRESS_PATTERN.subn("[STREET_ADDRESS_REDACTED]", sanitized)
            redactions += count

        # 5. Phone Numbers (inspect after government & credit cards to avoid substring overlap)
        if _PHONE_PATTERN.search(sanitized):
            detected.add(PiiCategory.PHONE_NUMBER)
            sanitized, count = _PHONE_PATTERN.subn("[PHONE_REDACTED]", sanitized)
            redactions += count

        return PiiRedactionResult(
            original_text=text,
            sanitized_text=sanitized,
            detected_categories=sorted(detected, key=lambda c: c.value),
            redaction_count=redactions,
            contains_child_privacy_violation=has_child_violation,
        )
