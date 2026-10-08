"""High-precision PII entity detector recognizing identity, financial, and contact identifiers.

[INPUT]
- Raw string text or tabular cells

[OUTPUT]
- List of non-overlapping PiiEntityMatch objects with coordinates and entity types.

[POS]
Harness core security module for client-side privacy preservation (Client-Side PII Sniffer).
"""

from __future__ import annotations

import re

from myrm_agent_harness.core.security.pii_vault.types import (
    PiiEntityMatch,
    PiiEntityType,
)

# 1. 18-digit Chinese National ID Card (公民身份号码)
_ID_CARD_REGEX: re.Pattern[str] = re.compile(
    r"\b[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b"
)

# 2. Chinese 11-digit mobile phone number (手机号)
_PHONE_REGEX: re.Pattern[str] = re.compile(
    r"(?:\+86\s*|86\s*)?\b1[3-9]\d{9}\b"
)

# 3. Standard Email address (电子邮箱)
_EMAIL_REGEX: re.Pattern[str] = re.compile(
    r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b"
)

# 4. Bank Card Number (16-19 digits, 银联/Visa/MasterCard)
_BANK_CARD_REGEX: re.Pattern[str] = re.compile(
    r"\b(?:62\d{14,17}|4\d{15}|5[1-5]\d{14})\b"
)

# 5. Chinese Name in labeled context (姓名/名字/学生/教师)
_LABELED_NAME_REGEX: re.Pattern[str] = re.compile(
    r"(?:姓名|名字|学生|教师|用户|联系人)[：:\s]+([\u4e00-\u9fa5]{2,4})\b"
)

# 6. Student/Employee ID (学号/工号)
_LABELED_STUDENT_ID_REGEX: re.Pattern[str] = re.compile(
    r"(?:学号|工号|证件号)[：:\s]+([0-9a-zA-Z]{6,16})\b"
)


class PiiEntityDetector:
    """Detects Chinese and international PII entities in unstructured or tabular text."""

    @classmethod
    def detect_entities(cls, text: str) -> list[PiiEntityMatch]:
        """Scan text and return a sorted list of non-overlapping detected PII entities."""
        if not text:
            return []

        raw_matches: list[tuple[int, int, PiiEntityType, str]] = []

        # 1. ID Cards
        for m in _ID_CARD_REGEX.finditer(text):
            raw_matches.append((m.start(), m.end(), PiiEntityType.ID_CARD, m.group(0)))

        # 2. Phone Numbers
        for m in _PHONE_REGEX.finditer(text):
            raw_matches.append((m.start(), m.end(), PiiEntityType.PHONE_NUMBER, m.group(0)))

        # 3. Emails
        for m in _EMAIL_REGEX.finditer(text):
            raw_matches.append((m.start(), m.end(), PiiEntityType.EMAIL, m.group(0)))

        # 4. Bank Cards
        for m in _BANK_CARD_REGEX.finditer(text):
            raw_matches.append((m.start(), m.end(), PiiEntityType.BANK_CARD, m.group(0)))

        # 5. Labeled Chinese Names
        for m in _LABELED_NAME_REGEX.finditer(text):
            name_val = m.group(1)
            start_pos = m.start(1)
            end_pos = m.end(1)
            raw_matches.append((start_pos, end_pos, PiiEntityType.CHINESE_NAME, name_val))

        # 6. Labeled Student/Employee IDs
        for m in _LABELED_STUDENT_ID_REGEX.finditer(text):
            id_val = m.group(1)
            start_pos = m.start(1)
            end_pos = m.end(1)
            raw_matches.append((start_pos, end_pos, PiiEntityType.STUDENT_ID, id_val))

        # Sort primarily by start index, secondarily by length descending (longer match takes priority)
        raw_matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))

        # Filter overlapping intervals
        filtered_matches: list[PiiEntityMatch] = []
        last_end = -1
        type_counters: dict[PiiEntityType, int] = {t: 0 for t in PiiEntityType}

        for start, end, entity_type, val in raw_matches:
            if start >= last_end:
                type_counters[entity_type] += 1
                counter = type_counters[entity_type]
                placeholder = f"[{entity_type.upper()}_{counter}]"
                filtered_matches.append(
                    PiiEntityMatch(
                        entity_type=entity_type,
                        raw_value=val,
                        placeholder=placeholder,
                        start_idx=start,
                        end_idx=end,
                    )
                )
                last_end = end

        return filtered_matches
