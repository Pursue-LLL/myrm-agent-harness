"""PII redactor — type-aware personal information masking.

Replaces detected PII with human-readable, type-tagged placeholders
while preserving enough structure for debugging (e.g., phone area code,
email domain). All redaction is irreversible by design — the original
values are never stored.

[INPUT]
- core.security.detection.card_context::find_card_number_spans (POS: Keyword-anchored detector for card numbers outside the network prefix table or with a typo in them.)
- core.security.detection.custom_rules::CustomRules, NO_CUSTOM_RULES, find_custom_spans (POS: Single definition of custom-term matching for the privacy policy: the PII classifier, the redactor and the pseudonymizer share it, so detection and masking never disagree about what a user's keyword or pattern covers.)
- core.security.detection.pii_patterns::compiled PII patterns and validators (POS: Single definition of the built-in PII patterns and their validators.)
- core.security.detection.password_heuristic::find_password_spans (POS: last-resort keyword-anchored detector for passwords without vendor prefix or entropy.)

[OUTPUT]
- redact_pii(): apply the PII redactions of the given levels (both by default), and optionally the user's custom keywords and patterns, to text; returns (redacted_text, redacted_count)
- redact_value(): redact a single known PII value by type

[POS]
PII redactor. Type-aware smart masking (phone numbers retain first 3 and last 4 digits, emails retain domain, etc.) for user-friendly redaction. Passwords are replaced by span (password_heuristic, recall mode) before the regex stages, so the label and the punctuation around the value survive. The user's custom terms are replaced by span right after the passwords.

"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from myrm_agent_harness.core.security.detection.card_context import find_card_number_spans
from myrm_agent_harness.core.security.detection.custom_rules import NO_CUSTOM_RULES, CustomRules, find_custom_spans
from myrm_agent_harness.core.security.detection.password_heuristic import find_password_spans
from myrm_agent_harness.core.security.detection.pii_patterns import (
    BANK_CARD_RE,
    CHINA_ADDRESS_RE,
    CHINA_COURIER_RE,
    CHINA_ID_RE,
    CHINA_PASSPORT_RE,
    CHINA_PHONE_RE,
    CREDIT_CARD_VISIBLE_RE,
    EMAIL_RE,
    INTL_PHONE_RE,
    PRIVATE_IP_RE,
    SSN_RE,
    US_PHONE_RE,
    china_id_valid,
    is_placeholder,
    luhn_valid,
)
from myrm_agent_harness.core.security.types import SensitivityLevel

# ---------------------------------------------------------------------------
# Type-aware redaction functions
# ---------------------------------------------------------------------------


def _redact_china_phone(m: re.Match[str]) -> str:
    number = re.sub(r"\D", "", m.group(0))[-11:]  # the match may start with the +86 country code
    return f"{number[:3]}****{number[-4:]} [PII:phone]"


def _redact_intl_phone(m: re.Match[str]) -> str:
    val = m.group(0)
    if len(val) > 8:
        return f"{val[:4]}***{val[-3:]} [PII:phone]"
    return "[PII:phone]"


def _redact_us_phone(m: re.Match[str]) -> str:
    return f"***-***-{m.group(0)[-4:]} [PII:phone]"


def _redact_email(m: re.Match[str]) -> str:
    val = m.group(0)
    at_idx = val.index("@")
    local = val[:at_idx]
    domain = val[at_idx:]
    if len(local) > 1:
        return f"{local[0]}***{domain} [PII:email]"
    return f"***{domain} [PII:email]"


def _redact_china_id(m: re.Match[str]) -> str:
    val = m.group(0)
    if not china_id_valid(val):
        return val
    return f"{val[:6]}********{val[-4:]} [PII:id_card]"


def _mask_bank_card(digits: str) -> str:
    return f"**** **** **** {digits[-4:]} [PII:bank_card]"


def _redact_bank_card(m: re.Match[str]) -> str:
    val = m.group(0)
    cleaned = val.replace("-", "").replace(" ", "")
    if not luhn_valid(cleaned):
        return val
    return _mask_bank_card(cleaned)


def _redact_credit_card(m: re.Match[str]) -> str:
    val = m.group(0)
    cleaned = val.replace("-", "").replace(" ", "")
    return f"**** **** **** {cleaned[-4:]} [PII:credit_card]"


def _replace_spans(content: str, bounds: Iterable[tuple[int, int]], marker: str) -> str:
    """*content* with each sorted, disjoint ``(start, end)`` range replaced by *marker*."""
    parts: list[str] = []
    cursor = 0
    for start, end in bounds:
        parts.append(content[cursor:start])
        parts.append(marker)
        cursor = end
    parts.append(content[cursor:])
    return "".join(parts)


def _redact_passwords(content: str) -> tuple[str, int]:
    """Replace each password value with a marker, keeping the label and the punctuation around the value."""
    spans = find_password_spans(content, strict=False)
    if not spans:
        return content, 0
    return _replace_spans(content, spans, "[REDACTED] [PII:password]"), len(spans)


def _redact_card_numbers(content: str) -> tuple[str, int]:
    """Mask each card number the text introduces with a card keyword, as the prefix table masks the cards it knows."""
    spans = find_card_number_spans(content)
    if not spans:
        return content, 0
    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.append(content[cursor:start])
        parts.append(_mask_bank_card(re.sub(r"\D", "", content[start:end])))
        cursor = end
    parts.append(content[cursor:])
    return "".join(parts), len(spans)


def _redact_custom(content: str, custom: CustomRules) -> tuple[str, int]:
    """Replace every span the user's custom keywords and patterns cover with a marker."""
    spans = find_custom_spans(content, custom)
    if not spans:
        return content, 0
    return _replace_spans(content, ((span.start, span.end) for span in spans), "[REDACTED] [PII:custom]"), len(spans)


def _redact_china_passport(m: re.Match[str]) -> str:
    val = m.group(0)
    return f"{val[0]}***{val[-3:]} [PII:passport]"


def _redact_private_ip(m: re.Match[str]) -> str:
    val = m.group(0)
    parts = val.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.***.*** [PII:private_ip]"
    return "[PII:private_ip]"


def _redact_china_address(m: re.Match[str]) -> str:
    val = m.group(0)
    if len(val) > 6:
        return f"{val[:4]}*** [PII:address]"
    return "[PII:address]"


def _redact_courier(m: re.Match[str]) -> str:
    val = m.group(0)
    return f"{val[:2]}***{val[-3:]} [PII:courier]"


def _redact_ssn(m: re.Match[str]) -> str:
    val = m.group(0)
    return f"***-**-{val[-4:]} [PII:ssn]"


# ---------------------------------------------------------------------------
# Ordered redaction pipeline: S3 first, then S2
# ---------------------------------------------------------------------------

_Redaction = tuple[str, re.Pattern[str], Callable[[re.Match[str]], str], bool]

# Order matters: more specific first.
_S3_REDACTIONS: tuple[_Redaction, ...] = (
    ("china_id_card", CHINA_ID_RE, _redact_china_id, True),
    ("bank_card", BANK_CARD_RE, _redact_bank_card, True),
    ("china_passport", CHINA_PASSPORT_RE, _redact_china_passport, False),
)

_S2_REDACTIONS: tuple[_Redaction, ...] = (
    ("china_phone", CHINA_PHONE_RE, _redact_china_phone, False),
    ("intl_phone", INTL_PHONE_RE, _redact_intl_phone, False),
    ("us_phone", US_PHONE_RE, _redact_us_phone, False),
    ("email", EMAIL_RE, _redact_email, False),
    ("credit_card_visible", CREDIT_CARD_VISIBLE_RE, _redact_credit_card, False),
    ("private_ip", PRIVATE_IP_RE, _redact_private_ip, False),
    ("china_address", CHINA_ADDRESS_RE, _redact_china_address, False),
    ("china_courier", CHINA_COURIER_RE, _redact_courier, False),
    ("us_ssn", SSN_RE, _redact_ssn, False),
)

_REDACTION_PIPELINE: tuple[_Redaction, ...] = (*_S3_REDACTIONS, *_S2_REDACTIONS)

ALL_LEVELS: frozenset[SensitivityLevel] = frozenset({SensitivityLevel.S2, SensitivityLevel.S3})


def _apply_redactions(content: str, redactions: tuple[_Redaction, ...]) -> tuple[str, int]:
    """*content* with each redaction applied in order; a match its validator rejects (Luhn, ID checksum) stays."""
    result = content
    total = 0
    for _name, pattern, redact_fn, check_placeholder in redactions:
        parts: list[str] = []
        cursor = 0
        count = 0
        for m in pattern.finditer(result):
            val = m.group(0)
            if check_placeholder and is_placeholder(val):
                continue
            redacted = redact_fn(m)
            if redacted == val:
                continue
            parts.append(result[cursor : m.start()])
            parts.append(redacted)
            cursor = m.end()
            count += 1
        if count:
            parts.append(result[cursor:])
            result = "".join(parts)
            total += count
    return result, total


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def redact_pii(
    content: str, custom: CustomRules = NO_CUSTOM_RULES, levels: frozenset[SensitivityLevel] = ALL_LEVELS
) -> tuple[str, int]:
    """Apply the PII redactions of *levels* to text content.

    Returns (redacted_text, count_of_redactions). Safe to call on any
    text — returns unchanged content with count=0 if nothing is found.

    Redaction order: passwords first (a value the text labels as a password wins
    over whatever pattern it also matches), then the user's *custom* keywords and
    patterns, then S3 patterns (identity docs, financial), then S2 patterns
    (contact info, location). Placeholder values are skipped to avoid false
    positives. Without *custom* only the built-in detectors apply.

    *levels* narrows the built-in detectors: S3 covers passwords, identity documents, bank cards and credentials, S2
    the contact and location patterns. A caller that applies a different action per level passes one level at a time,
    so a level whose action is to leave the text alone never loses content to another level's redaction. *custom* is
    applied whatever *levels* is: the caller hands over the terms of the level it is acting on.
    """
    if not content:
        return content, 0

    confidential = SensitivityLevel.S3 in levels
    result, total_count = _redact_passwords(content) if confidential else (content, 0)
    result, custom_count = _redact_custom(result, custom)
    total_count += custom_count

    if confidential:
        result, count = _apply_redactions(result, _S3_REDACTIONS)
        total_count += count
        result, count = _redact_card_numbers(result)
        total_count += count
    if SensitivityLevel.S2 in levels:
        result, count = _apply_redactions(result, _S2_REDACTIONS)
        total_count += count

    # Also apply leak_detector redaction for credentials
    from myrm_agent_harness.agent.security.detection.leak_detector import redact_leaks, scan_for_leaks

    leak_matches = scan_for_leaks(result) if confidential else []
    if leak_matches:
        result = redact_leaks(result)
        total_count += len(leak_matches)

    return result, total_count


def redact_value(value: str, pii_type: str) -> str:
    """Redact a single known PII value by type name.

    Useful when you already know the PII type from classification.
    Returns the redacted string.
    """
    for _name, pattern, redact_fn, _check in _REDACTION_PIPELINE:
        if _name == pii_type:
            m = pattern.search(value)
            if m:
                return redact_fn(m)
    return f"[PII:{pii_type}]"
