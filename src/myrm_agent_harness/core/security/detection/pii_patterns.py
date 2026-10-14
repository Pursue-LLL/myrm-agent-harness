"""PII pattern tables and validators — what the built-in detectors look for, and how a hit is confirmed.

The classifier decides what a text is, the redactor masks it and the pseudonymizer replaces it; all three read these
tables, so a value that is detected is a value that is masked. Passwords, credentials and the card numbers a card
keyword introduces are not pattern-table entries: they are found by span (password_heuristic, leak_detector,
card_context).

All patterns are pre-compiled module-level constants; the validators are pure functions.

[INPUT]
- core.security.detection.iban::IBAN_RE, iban_valid, inside_iban (POS: IBAN detection for the PII pattern tables. The lengths are those of the SWIFT IBAN registry (89 countries). Typed with hyphens or other separators, an IBAN is not matched.)

[OUTPUT]
- S3_PATTERNS / S2_PATTERNS: (name, pattern) tables of the confidential and sensitive built-in regex detectors
- the individual patterns (CHINA_ID_RE, BANK_CARD_RE, CHINA_PHONE_RE, ...), which the redactor pairs with its masks
- is_confirmed(): whether a pattern match is a real hit: it survives the checksum its type calls for (identity number, bank card, IBAN) and a card number is not part of an IBAN
- bank_card_valid(), luhn_valid(), china_id_valid(): the checksums themselves
- is_placeholder(): whether a value is an obvious example ("test", "user@example.com") rather than real data

[POS]
Single definition of the built-in PII patterns and their validators: classification, redaction and pseudonymization
all read it, so they never disagree about what a hit is.
"""

from __future__ import annotations

import re

from myrm_agent_harness.core.security.detection.iban import IBAN_RE, iban_valid, inside_iban

# ---------------------------------------------------------------------------
# S3 patterns — confidential (identity documents, financial accounts)
# ---------------------------------------------------------------------------

CHINA_ID_RE = re.compile(
    r"(?<!\d)"
    r"[1-9]\d{5}"
    r"(?:19|20)\d{2}"
    r"(?:0[1-9]|1[0-2])"
    r"(?:0[1-9]|[12]\d|3[01])"
    r"\d{3}[\dXx]"
    r"(?!\d)"
)

# Leading digits of the major card networks: Visa 4, Mastercard 51-55 and 2221-2720, UnionPay 62, Amex 34/37,
# JCB 3528-3589, Discover 6011/644-649/65.
_CARD_PREFIX = r"(?:4|5[1-5]|62|3[47]|2(?:22[1-9]|2[3-9]\d|[3-6]\d\d|7[01]\d|720)|35(?:2[89]|[3-8]\d)|6011|64[4-9]|65)"

# One run of 15-19 digits, or typed with the same hyphen or space between the groups: four of four
# (4532 0151 1283 0366), the UnionPay form with a fifth of three (the five-group form is tried first), Amex as 4-6-5
# (3782 822463 10005). Only these separators: every Luhn check strips just them. The fifth group is exactly three
# digits so that the expiry date typed after a card (4532 0151 1283 0366 12/28) is not read as part of it.
BANK_CARD_RE = re.compile(
    r"(?<!\d)(?=\d)(?:"
    rf"(?={_CARD_PREFIX})\d{{15,19}}"
    r"|62\d{2}(?P<sep19>[- ])\d{4}(?P=sep19)\d{4}(?P=sep19)\d{4}(?P=sep19)\d{3}"
    rf"|(?={_CARD_PREFIX})\d{{4}}(?P<sep16>[- ])\d{{4}}(?P=sep16)\d{{4}}(?P=sep16)\d{{4}}"
    r"|3[47]\d{2}(?P<sep15>[- ])\d{6}(?P=sep15)\d{5}"
    r")(?!\d)"
)

CHINA_PASSPORT_RE = re.compile(
    r"(?<![A-Za-z])"
    r"[EeGg]\d{8}"
    r"(?![A-Za-z\d])"
)

S3_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("china_id_card", CHINA_ID_RE),
    ("bank_card", BANK_CARD_RE),
    ("china_passport", CHINA_PASSPORT_RE),
)

# ---------------------------------------------------------------------------
# S2 patterns — sensitive (personal contact, location, bank account)
# ---------------------------------------------------------------------------

# Eleven digits, or typed in groups of 3-4-4 (138 0013 8000, 138-0013-8000). A typed number does not follow a
# letter: the tail of a UUID (dd75f159-9266-4208) is not a phone number.
CHINA_PHONE_RE = re.compile(
    r"(?<!\d)"
    r"(?:\+?86[-\s]?)?"
    r"1[3-9]\d(?:\d{8}|(?<![A-Za-z]1[3-9]\d)[- ]\d{4}[- ]\d{4})"
    r"(?!\d)"
)

INTL_PHONE_RE = re.compile(r"\+\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}")

# A US number written without the country code: (415) 555-2671, 415-555-2671, 415.555.2671, optionally led by the
# trunk prefix "1-". Area code and exchange do not start with 0 or 1. It is not part of a longer token, and it does
# not follow a "+<country code>", which the international pattern reads (a number is never found by both).
US_PHONE_RE = re.compile(
    r"(?<![\w.+-])(?<!\+\d[ .-])(?<!\+\d{2}[ .-])(?<!\+\d{3}[ .-])"
    r"(?:1[-. ])?(?:\([2-9]\d{2}\)[ -]?|[2-9]\d{2}[-. ])"
    r"[2-9]\d{2}[-. ]\d{4}(?![\w-])"
)

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

CREDIT_CARD_VISIBLE_RE = re.compile(
    r"(?<!\d)"
    r"\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}"
    r"(?!\d)"
)

PRIVATE_IP_RE = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3})\b"
)

CHINA_ADDRESS_RE = re.compile(
    r"(?:"
    r"(?:北京|上海|天津|重庆|[^\s]{2,4}(?:省|自治区))"
    r".{0,6}(?:市|区|县|镇|乡|街道|路|号|弄|栋|楼|室|单元)"
    r"|"
    r"(?:市|区|县).{0,10}(?:路|街|道|巷|弄).{0,6}(?:号|栋|楼|室)"
    r")"
)

CHINA_COURIER_RE = re.compile(
    r"(?:SF|YT|YD|ZT|EMS|YZPY|JD|DBL|YUNDA|STO|ZTO|BEST)"
    r"\d{10,15}",
    re.IGNORECASE,
)

SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")

# An IBAN names an account (money can be sent to it) but, unlike a card number, does not authorise a payment from it,
# so it is S2. It comes first: typed in groups, its digits also look like a visible card number.
S2_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("iban", IBAN_RE),
    ("china_phone", CHINA_PHONE_RE),
    ("intl_phone", INTL_PHONE_RE),
    ("us_phone", US_PHONE_RE),
    ("email", EMAIL_RE),
    ("credit_card_visible", CREDIT_CARD_VISIBLE_RE),
    ("private_ip", PRIVATE_IP_RE),
    ("china_address", CHINA_ADDRESS_RE),
    ("china_courier", CHINA_COURIER_RE),
    ("us_ssn", SSN_RE),
)

# ---------------------------------------------------------------------------
# Placeholder exclusion (reuse logic from leak_detector)
# ---------------------------------------------------------------------------

PLACEHOLDER_RE = re.compile(
    r"^(?:your[_-].*|xxx+|placeholder|example|changeme|TODO|CHANGE_ME|INSERT_HERE|"
    r"<[^>]+>|\$\{[^}]+\}|%\([^)]+\)s|None|null|undefined|test|demo|fake|dummy|sample"
    r"|user@example\.com|john@doe\.com|test@test\.com|admin@admin\.com"
    r"|12345678901|00000000000|11111111111"
    r")$",
    re.IGNORECASE,
)


def is_placeholder(value: str) -> bool:
    """Whether *value* is an obvious example or template value rather than real data."""
    return bool(PLACEHOLDER_RE.match(value.strip()))


# ---------------------------------------------------------------------------
# Luhn checksum (bank card / credit card validation)
# ---------------------------------------------------------------------------


def luhn_valid(digits: str) -> bool:
    """Validate a digit string against the Luhn algorithm; anything but decimal digits fails."""
    if not digits.isdecimal() or len(digits) < 13:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def bank_card_valid(value: str) -> bool:
    """Whether a bank-card match passes the Luhn check, typed with or without the hyphens or spaces between groups."""
    return luhn_valid(value.replace("-", "").replace(" ", ""))


# ---------------------------------------------------------------------------
# ID card checksum (China 18-digit)
# ---------------------------------------------------------------------------

_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK_CODES = "10X98765432"


def china_id_valid(id_str: str) -> bool:
    """Validate China 18-digit ID card number with checksum."""
    if len(id_str) != 18:
        return False
    body = id_str[:17]
    if not body.isdecimal():
        return False
    total = sum(int(body[i]) * _ID_WEIGHTS[i] for i in range(17))
    expected = _ID_CHECK_CODES[total % 11]
    return id_str[17].upper() == expected


def is_confirmed(name: str, match: re.Match[str]) -> bool:
    """Whether *match* of the pattern *name* is a real hit; a pattern without a rule always is.

    A national ID, a bank card and an IBAN must survive their checksum. A card number that lies within a valid IBAN is
    a run of the account number, not a card: a few percent of the digit-only IBANs typed in groups read as one.
    """
    value = match.group(0)
    if name == "china_id_card":
        return china_id_valid(value)
    if name == "bank_card":
        return bank_card_valid(value) and not inside_iban(match.string, match.start(), match.end())
    if name == "iban":
        return iban_valid(value)
    return True
