"""
[INPUT]: Raw memory text to be ingested into long-term storage
[OUTPUT]: PiiShieldDetection inspecting and masking children names, precise addresses, and financial PII
[POS]: myrm_agent_harness.toolkits.memory.verifiable_provenance.pre_ingest_pii_shield
"""

from __future__ import annotations

import re
from typing import List

from .models import PiiCategory, PiiShieldDetection

_CHILD_PATTERN = re.compile(
    r"(?i)\b((?:my\s+(?:son|daughter|kid|child|toddler)(?:'s\s+name)?|child(?:ren)?(?:'s)?\s+name)\s*(?:is|:|=)?)\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
)
_ADDRESS_PATTERN = re.compile(
    r"(?i)\b(?:home\s+address|street|address|zip\s+code|postal\s+code)\s*[:=]\s*([^,\n;\.]{2,40})",
)
_FINANCIAL_PATTERN = re.compile(
    r"(?i)\b(?:credit\s+card|bank\s+account|account\s+number|iban|routing\s+number)\s*[:=]\s*([a-zA-Z0-9\- ]{8,30})",
)
_SSN_PATTERN = re.compile(
    r"(?i)\b(?:ssn|social security number|national id|id card)\s*[:=]\s*(\d{3}-\d{2}-\d{4}|\d{9,18})",
)


class PreIngestPiiShield:
    """Intercepts and anonymizes high-risk PII before entering persistent memory storage."""

    def inspect_and_mask(self, text: str) -> PiiShieldDetection:
        """Scan text for sensitive PII entities and produce a sanitized projection."""
        sanitized = text
        categories: List[PiiCategory] = []
        masked_spans: List[str] = []
        has_child = False

        # 1. Child Identity Check
        def _mask_child(match: re.Match[str]) -> str:
            nonlocal has_child
            has_child = True
            prefix = match.group(1).strip()
            target = match.group(2).strip()
            masked_spans.append(target)
            return f"{prefix} [REDACTED_CHILD_IDENTITY]"

        if _CHILD_PATTERN.search(sanitized):
            categories.append(PiiCategory.CHILD_IDENTITY)
            sanitized = _CHILD_PATTERN.sub(_mask_child, sanitized)

        # 2. Precise Residential Address Check
        def _mask_address(match: re.Match[str]) -> str:
            target = match.group(1).strip()
            masked_spans.append(target)
            return "address: [REDACTED_RESIDENTIAL_ADDRESS]"

        if _ADDRESS_PATTERN.search(sanitized):
            categories.append(PiiCategory.PRECISE_RESIDENTIAL_ADDRESS)
            sanitized = _ADDRESS_PATTERN.sub(_mask_address, sanitized)

        # 3. Financial Instruments
        def _mask_fin(match: re.Match[str]) -> str:
            target = match.group(1).strip()
            masked_spans.append(target)
            return "financial_account: [REDACTED_FINANCIAL_INSTRUMENT]"

        if _FINANCIAL_PATTERN.search(sanitized):
            categories.append(PiiCategory.FINANCIAL_INSTRUMENT)
            sanitized = _FINANCIAL_PATTERN.sub(_mask_fin, sanitized)

        # 4. Government IDs
        def _mask_id(match: re.Match[str]) -> str:
            target = match.group(1).strip()
            masked_spans.append(target)
            return "national_id: [REDACTED_GOVERNMENT_ID]"

        if _SSN_PATTERN.search(sanitized):
            categories.append(PiiCategory.GOVERNMENT_ID)
            sanitized = _SSN_PATTERN.sub(_mask_id, sanitized)

        intercepted = len(categories) > 0

        return PiiShieldDetection(
            intercepted=intercepted,
            detected_categories=categories,
            sanitized_text=sanitized,
            masked_spans=masked_spans,
            has_child_privacy_violation=has_child,
        )
