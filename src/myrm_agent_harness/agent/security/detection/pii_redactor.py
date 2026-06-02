"""PII redactor — type-aware personal information masking.

Replaces detected PII with human-readable, type-tagged placeholders
while preserving enough structure for debugging (e.g., phone area code,
email domain). All redaction is irreversible by design — the original
values are never stored.

[INPUT]

[OUTPUT]
- redact_pii(): apply all PII redactions to text, returns (redacted_text, redacted_count)
- redact_value(): redact a single known PII value by type

[POS]
PII redactor. Type-aware smart masking (phone numbers retain first 3 and last 4 digits, emails retain domain, etc.) for user-friendly redaction.

"""

from __future__ import annotations

import re

from myrm_agent_harness.core.security.detection.pii_classifier import (
    _BANK_CARD_RE,
    _CHINA_ADDRESS_RE,
    _CHINA_COURIER_RE,
    _CHINA_ID_RE,
    _CHINA_PASSPORT_RE,
    _CHINA_PHONE_RE,
    _CREDIT_CARD_VISIBLE_RE,
    _EMAIL_RE,
    _INTL_PHONE_RE,
    _PASSWORD_CONTEXT_RE,
    _PLACEHOLDER_RE,
    _PRIVATE_IP_RE,
    _SSN_RE,
    _china_id_valid,
    _luhn_valid,
)

# ---------------------------------------------------------------------------
# Type-aware redaction functions
# ---------------------------------------------------------------------------


def _redact_china_phone(m: re.Match[str]) -> str:
    val = m.group(0)
    digits = re.sub(r"\D", "", val)
    if len(digits) >= 11:
        return f"{digits[:3]}****{digits[-4:]} [PII:phone]"
    return "[PII:phone]"


def _redact_intl_phone(m: re.Match[str]) -> str:
    val = m.group(0)
    if len(val) > 8:
        return f"{val[:4]}***{val[-3:]} [PII:phone]"
    return "[PII:phone]"


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
    if not _china_id_valid(val):
        return val
    return f"{val[:6]}********{val[-4:]} [PII:id_card]"


def _redact_bank_card(m: re.Match[str]) -> str:
    val = m.group(0)
    cleaned = val.replace("-", "").replace(" ", "")
    if not _luhn_valid(cleaned):
        return val
    return f"**** **** **** {cleaned[-4:]} [PII:bank_card]"


def _redact_credit_card(m: re.Match[str]) -> str:
    val = m.group(0)
    cleaned = val.replace("-", "").replace(" ", "")
    return f"**** **** **** {cleaned[-4:]} [PII:credit_card]"


def _redact_password(m: re.Match[str]) -> str:
    prefix = m.group(0)
    password_val = m.group(1) if m.lastindex else ""
    if password_val:
        redacted = prefix.replace(password_val, "[REDACTED]", 1)
        return f"{redacted} [PII:password]"
    return "[PII:password]"


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


def _is_placeholder(val: str) -> bool:
    return bool(_PLACEHOLDER_RE.match(val.strip()))


# ---------------------------------------------------------------------------
# Ordered redaction pipeline: S3 first, then S2
# ---------------------------------------------------------------------------

_REDACTION_PIPELINE: tuple[tuple[str, re.Pattern[str], object, bool], ...] = (
    # S3 patterns (order matters: more specific first)
    ("china_id_card", _CHINA_ID_RE, _redact_china_id, True),
    ("bank_card", _BANK_CARD_RE, _redact_bank_card, True),
    ("password_context", _PASSWORD_CONTEXT_RE, _redact_password, False),
    ("china_passport", _CHINA_PASSPORT_RE, _redact_china_passport, False),
    # S2 patterns
    ("china_phone", _CHINA_PHONE_RE, _redact_china_phone, False),
    ("intl_phone", _INTL_PHONE_RE, _redact_intl_phone, False),
    ("email", _EMAIL_RE, _redact_email, False),
    ("credit_card_visible", _CREDIT_CARD_VISIBLE_RE, _redact_credit_card, False),
    ("private_ip", _PRIVATE_IP_RE, _redact_private_ip, False),
    ("china_address", _CHINA_ADDRESS_RE, _redact_china_address, False),
    ("china_courier", _CHINA_COURIER_RE, _redact_courier, False),
    ("us_ssn", _SSN_RE, _redact_ssn, False),
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def redact_pii(content: str) -> tuple[str, int]:
    """Apply all PII redactions to text content.

    Returns (redacted_text, count_of_redactions). Safe to call on any
    text — returns unchanged content with count=0 if nothing is found.

    Redaction order: S3 patterns first (identity docs, financial),
    then S2 patterns (contact info, location). Placeholder values are
    skipped to avoid false positives.
    """
    if not content:
        return content, 0

    result = content
    total_count = 0

    for _name, pattern, redact_fn, check_placeholder in _REDACTION_PIPELINE:
        new_result_parts: list[str] = []
        cursor = 0
        count = 0

        for m in pattern.finditer(result):
            val = m.group(0)
            if check_placeholder and _is_placeholder(val):
                continue
            new_result_parts.append(result[cursor : m.start()])
            new_result_parts.append(redact_fn(m))
            cursor = m.end()
            count += 1

        if count > 0:
            new_result_parts.append(result[cursor:])
            result = "".join(new_result_parts)
            total_count += count

    # Also apply leak_detector redaction for credentials
    from myrm_agent_harness.agent.security.detection.leak_detector import redact_leaks, scan_for_leaks

    leak_matches = scan_for_leaks(result)
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
