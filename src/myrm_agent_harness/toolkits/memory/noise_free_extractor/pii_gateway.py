"""[POS]: src/myrm_agent_harness/toolkits/memory/noise_free_extractor/pii_gateway.py
[INPUT]:
- core.security.detection.pii_patterns::BANK_CARD_RE, CHINA_ID_RE, SSN_RE, is_confirmed, luhn_valid (POS: Single definition of the built-in PII patterns and their validators: classification, redaction and pseudonymization all read it, so they never disagree about what a hit is.)
- core.security.detection.iban::IBAN_RE (POS: IBAN detection for the PII pattern tables. The lengths are those of the SWIFT IBAN registry (89 countries). Typed with hyphens or other separators, an IBAN is not matched.)
- core.security.detection.card_context::find_card_number_spans, find_card_shaped_spans (POS: Keyword-anchored detector for card numbers outside the network prefix table or with a typo in them.)
- core.security.detection.password_heuristic::find_password_spans (POS: Last-resort detector for secrets that carry no vendor prefix and no high entropy.)
- core.security.detection.leak_detector::scan_for_leaks, redact_leaks (POS: Output-side credential leak detector.)
[OUTPUT]: PIISafetyGateway: whether a candidate memory statement may be stored, its masked text, and the PII violations found.

Storage gate in front of persistent memory. It reads the detectors of the privacy pipeline, so a number the pipeline
masks is a number the gate refuses, and it is stricter in three ways, because a statement that slips through is stored
for good while one that is refused costs a single fact: a 15 or 16 digit run that passes the Luhn check is a card
whatever network issued it, an ID or IBAN with a mistyped check digit is still an identifier, and a value assigned to
a bare "secret" label is a credential. It does not depend on the user's privacy policy: switching privacy off never
lets a card number into memory.
"""

import re
from bisect import bisect_left
from dataclasses import dataclass
from typing import Literal

from myrm_agent_harness.core.security.detection.card_context import find_card_number_spans, find_card_shaped_spans
from myrm_agent_harness.core.security.detection.iban import IBAN_RE
from myrm_agent_harness.core.security.detection.leak_detector import redact_leaks, scan_for_leaks
from myrm_agent_harness.core.security.detection.password_heuristic import find_password_spans
from myrm_agent_harness.core.security.detection.pii_patterns import (
    BANK_CARD_RE,
    CHINA_ID_RE,
    SSN_RE,
    is_confirmed,
    luhn_valid,
)
from myrm_agent_harness.core.security.detection.secret_value import Span

from .types import PIIViolationDetail, SanitizedExtractionResult

_Severity = Literal["high", "critical"]

_CREDIT_CARD = "credit_card"
_IBAN = "iban"
_SSN = "ssn_us"
_NATIONAL_ID = "national_id_cn"
_SECRET = "secret_token_key"
_CREDENTIAL = "plaintext_credential"

_SEVERITY: dict[str, _Severity] = {
    _CREDIT_CARD: "high",
    _IBAN: "critical",
    _SSN: "critical",
    _NATIONAL_ID: "critical",
    _SECRET: "critical",
    _CREDENTIAL: "critical",
}

_NON_DIGIT_RE = re.compile(r"\D")
# "secret" alone is an everyday word, so the privacy pipeline only reads "api secret" or "secret key" as a label.
_SECRET_LABEL_RE = re.compile(r"\bsecret\s*[:=]\s*(?P<value>[^\s,;]{6,})", re.IGNORECASE)
# Amex and the standard sixteen. A shorter or longer digit run is too often an order number or a timestamp to refuse on
# the checksum alone; the prefix table and the card keyword still catch those that are cards.
_UNLISTED_CARD_LENGTHS = frozenset({15, 16})
_FULLY_MASKED = "***"


@dataclass(frozen=True, slots=True)
class _Hit:
    rule: str
    span: Span


def _luhn_card_spans(text: str) -> list[Span]:
    spans: list[Span] = []
    for start, end in find_card_shaped_spans(text):
        digits = _NON_DIGIT_RE.sub("", text[start:end])
        if len(digits) in _UNLISTED_CARD_LENGTHS and luhn_valid(digits):
            spans.append((start, end))
    return spans


def _card_spans(text: str) -> list[Span]:
    return [
        *(match.span() for match in BANK_CARD_RE.finditer(text) if is_confirmed("bank_card", match)),
        *find_card_number_spans(text),
        *_luhn_card_spans(text),
    ]


def _credential_spans(text: str) -> list[Span]:
    return [
        *find_password_spans(text, strict=False),
        *(match.span("value") for match in _SECRET_LABEL_RE.finditer(text)),
    ]


def _candidate_spans(text: str) -> list[tuple[str, list[Span]]]:
    """Every rule's spans, identifiers first: a run of an IBAN or an ID is never read as a card inside it."""
    return [
        (_IBAN, [match.span() for match in IBAN_RE.finditer(text)]),
        (_NATIONAL_ID, [match.span() for match in CHINA_ID_RE.finditer(text)]),
        (_SSN, [match.span() for match in SSN_RE.finditer(text)]),
        (_CREDIT_CARD, _card_spans(text)),
        (_CREDENTIAL, _credential_spans(text)),
    ]


def _find_hits(text: str) -> list[_Hit]:
    """Disjoint hits in text order; where rules claim the same characters the earlier rule, then the longer span, wins."""
    hits: list[_Hit] = []
    starts: list[int] = []
    for rule, spans in _candidate_spans(text):
        for start, end in sorted(spans, key=lambda span: (span[0], -span[1])):
            # The accepted hits are disjoint and sorted, so only the two neighbours can overlap a new span.
            index = bisect_left(starts, start)
            if index > 0 and hits[index - 1].span[1] > start:
                continue
            if index < len(hits) and hits[index].span[0] < end:
                continue
            hits.insert(index, _Hit(rule, (start, end)))
            starts.insert(index, start)
    return hits


def _snippet(hit: _Hit, text: str) -> str:
    """The first and last two characters of an identifier for the audit trail; a credential is never shown."""
    if hit.rule == _CREDENTIAL:
        return _FULLY_MASKED
    value = text[hit.span[0] : hit.span[1]]
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def _mask(text: str, hits: list[_Hit], *, has_secrets: bool) -> str:
    pieces: list[str] = []
    cursor = 0
    for hit in hits:
        pieces.append(text[cursor : hit.span[0]])
        pieces.append(f"[{hit.rule}_REDACTED]")
        cursor = hit.span[1]
    pieces.append(text[cursor:])
    masked = "".join(pieces)
    return redact_leaks(masked) if has_secrets else masked


class PIISafetyGateway:
    """Screens extracted memory facts for card numbers, IBANs, national IDs, SSNs, passwords and API secrets."""

    def __init__(self, mask_instead_of_reject: bool = False) -> None:
        self.mask_instead_of_reject = mask_instead_of_reject

    def inspect(self, statement: str) -> SanitizedExtractionResult:
        """Find the PII in *statement*; in masking mode also return the statement with each hit replaced."""
        hits = _find_hits(statement)
        has_secrets = bool(scan_for_leaks(statement))
        violations = [
            PIIViolationDetail(
                rule_name=hit.rule, snippet_masked=_snippet(hit, statement), severity=_SEVERITY[hit.rule]
            )
            for hit in hits
        ]
        if has_secrets:
            violations.append(
                PIIViolationDetail(rule_name=_SECRET, snippet_masked=_FULLY_MASKED, severity=_SEVERITY[_SECRET])
            )
        sanitized = _mask(statement, hits, has_secrets=has_secrets) if self.mask_instead_of_reject else statement
        return SanitizedExtractionResult(is_clean=not violations, sanitized_text=sanitized, violations=violations)

    def is_safe_for_storage(self, statement: str) -> bool:
        """Whether *statement* holds nothing the gate refuses."""
        return self.inspect(statement).is_clean
