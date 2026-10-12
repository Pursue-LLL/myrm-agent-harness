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
_ZH_CHILD_PATTERN = re.compile(
    r"(我(?:儿子|女儿|孩子|小孩)(?:的名字)?(?:叫|是|为|：|:))\s*([\u4e00-\u9fa5]{2,6})",
)
_ADDRESS_PATTERN = re.compile(
    r"(?i)\b(?:home\s+address|street|address|zip\s+code|postal\s+code)\s*[:=]\s*([^,\n;\.]{2,40})",
)
_ZH_ADDRESS_PATTERN = re.compile(
    r"(家庭住址|居住地址|详细地址|家住|住址)\s*[:：=]\s*([^\n,，;；。]{4,50})",
)
_FINANCIAL_PATTERN = re.compile(
    r"(?i)\b(?:credit\s+card|bank\s+account|account\s+number|iban|routing\s+number)\s*[:=]\s*([a-zA-Z0-9\- ]{8,30})",
)
_ZH_FINANCIAL_PATTERN = re.compile(
    r"(银行卡号|信用卡号|银行卡尾号|信用卡尾号)\s*[:：=]?\s*([0-9\s\-]{4,30})",
)
_SSN_PATTERN = re.compile(
    r"(?i)\b(?:ssn|social security number|national id|id card)\s*[:=]\s*(\d{3}-\d{2}-\d{4}|\d{9,18})",
)
_ZH_ID_PATTERN = re.compile(
    r"(身份证号(?:码)?|身份证)\s*[:：=]?\s*([1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx])",
)


class PreIngestPiiShield:
    """Intercepts and anonymizes high-risk PII before entering persistent memory storage."""

    def inspect_and_mask(self, text: str) -> PiiShieldDetection:
        """Scan text for sensitive PII entities and produce a sanitized projection."""
        sanitized = text
        categories: List[PiiCategory] = []
        masked_spans: List[str] = []
        has_child = False

        # 1. Child Identity Check (English & Chinese)
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

        if _ZH_CHILD_PATTERN.search(sanitized):
            if PiiCategory.CHILD_IDENTITY not in categories:
                categories.append(PiiCategory.CHILD_IDENTITY)
            sanitized = _ZH_CHILD_PATTERN.sub(_mask_child, sanitized)

        # 2. Precise Residential Address Check (English & Chinese)
        def _mask_address(match: re.Match[str]) -> str:
            target = match.group(1).strip() if match.lastindex == 1 else match.group(2).strip()
            masked_spans.append(target)
            return "address: [REDACTED_RESIDENTIAL_ADDRESS]"

        if _ADDRESS_PATTERN.search(sanitized):
            categories.append(PiiCategory.PRECISE_RESIDENTIAL_ADDRESS)
            sanitized = _ADDRESS_PATTERN.sub(_mask_address, sanitized)

        if _ZH_ADDRESS_PATTERN.search(sanitized):
            if PiiCategory.PRECISE_RESIDENTIAL_ADDRESS not in categories:
                categories.append(PiiCategory.PRECISE_RESIDENTIAL_ADDRESS)
            sanitized = _ZH_ADDRESS_PATTERN.sub(_mask_address, sanitized)

        # 3. Financial Instruments (English & Chinese)
        def _mask_fin(match: re.Match[str]) -> str:
            target = match.group(1).strip() if match.lastindex == 1 else match.group(2).strip()
            masked_spans.append(target)
            return "financial_account: [REDACTED_FINANCIAL_INSTRUMENT]"

        if _FINANCIAL_PATTERN.search(sanitized):
            categories.append(PiiCategory.FINANCIAL_INSTRUMENT)
            sanitized = _FINANCIAL_PATTERN.sub(_mask_fin, sanitized)

        if _ZH_FINANCIAL_PATTERN.search(sanitized):
            if PiiCategory.FINANCIAL_INSTRUMENT not in categories:
                categories.append(PiiCategory.FINANCIAL_INSTRUMENT)
            sanitized = _ZH_FINANCIAL_PATTERN.sub(_mask_fin, sanitized)

        # 4. Government IDs (English & Chinese)
        def _mask_id(match: re.Match[str]) -> str:
            target = match.group(1).strip() if match.lastindex == 1 else match.group(2).strip()
            masked_spans.append(target)
            return "national_id: [REDACTED_GOVERNMENT_ID]"

        if _SSN_PATTERN.search(sanitized):
            categories.append(PiiCategory.GOVERNMENT_ID)
            sanitized = _SSN_PATTERN.sub(_mask_id, sanitized)

        if _ZH_ID_PATTERN.search(sanitized):
            if PiiCategory.GOVERNMENT_ID not in categories:
                categories.append(PiiCategory.GOVERNMENT_ID)
            sanitized = _ZH_ID_PATTERN.sub(_mask_id, sanitized)

        intercepted = len(categories) > 0

        return PiiShieldDetection(
            intercepted=intercepted,
            detected_categories=categories,
            sanitized_text=sanitized,
            masked_spans=masked_spans,
            has_child_privacy_violation=has_child,
        )
