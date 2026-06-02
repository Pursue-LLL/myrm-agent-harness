"""Pseudonymizer — reversible PII replacement with typed placeholders.

Converts detected PII items into semantically typed pseudonyms
(e.g. ``138-0013-8000`` → ``<PHONE_NUMBER_1>``) while preserving
context for the LLM.  Original values are persisted in the
``PseudonymStore`` for later restoration.

The ``PseudonymRestorer`` (bottom of this module) handles the reverse
direction — replacing pseudonyms back to originals in both batch and
streaming modes.

[INPUT]
- detection results from pii_classifier (PIIClassification)
- PseudonymStore for persistent mapping

[OUTPUT]
- pseudonymize_text(): replace PII in text with typed pseudonyms
- PseudonymRestorer: streaming-safe reverse mapping

[POS]
Reversible PII pseudonymization engine. Replaces detected PII with
typed placeholders via PseudonymStore, and provides a streaming-safe
restorer with chunk-boundary buffering.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from myrm_agent_harness.core.security.detection.pseudonym_store import (
    PseudonymStore,
)
from myrm_agent_harness.core.security.types import SensitivityLevel

_PATTERN_TO_TYPE: dict[str, str] = {
    # S3 patterns
    "china_id_card": "ID_CARD",
    "bank_card": "BANK_CARD",
    "password_context": "PASSWORD",
    "china_passport": "PASSPORT",
    # S2 patterns
    "china_phone": "PHONE_NUMBER",
    "intl_phone": "PHONE_NUMBER",
    "email": "EMAIL_ADDRESS",
    "credit_card_visible": "CREDIT_CARD",
    "private_ip": "PRIVATE_IP",
    "china_address": "ADDRESS",
    "china_courier": "COURIER_NUMBER",
    "us_ssn": "SSN",
}


@dataclass(frozen=True, slots=True)
class PIIItem:
    """A single PII detection result with position info."""

    original_text: str
    privacy_type: str
    level: SensitivityLevel
    start: int
    end: int


@dataclass(slots=True)
class PseudonymizeResult:
    """Result of pseudonymizing a text string."""

    text: str
    count: int = 0
    items: list[PIIItem] = field(default_factory=list)


def _extract_pii_items(
    content: str,
    level: SensitivityLevel,
) -> list[PIIItem]:
    """Extract PIIItems from *content* at the specified sensitivity *level*.

    Only returns items matching the requested level: S3 scans S3 patterns,
    S2 scans S2 patterns. This ensures pseudonymize_text respects the
    per-level action configured in PrivacyPolicy.
    """
    from myrm_agent_harness.core.security.detection.pii_classifier import (
        _PLACEHOLDER_RE,
        _S2_PATTERNS,
        _S3_PATTERNS,
        _china_id_valid,
        _luhn_valid,
    )

    items: list[PIIItem] = []
    seen_spans: set[tuple[int, int]] = set()
    s3_names = frozenset(name for name, _ in _S3_PATTERNS)

    if level == SensitivityLevel.S3:
        target_patterns = list(_S3_PATTERNS)
    elif level == SensitivityLevel.S2:
        target_patterns = list(_S2_PATTERNS)
    else:
        return items

    for name, pat in target_patterns:
        for m in pat.finditer(content):
            span = (m.start(), m.end())
            if span in seen_spans:
                continue
            val = m.group(0)
            if _PLACEHOLDER_RE.match(val.strip()):
                continue
            if name == "china_id_card" and not _china_id_valid(val):
                continue
            if name == "bank_card" and not _luhn_valid(
                val.replace("-", "").replace(" ", "")
            ):
                continue

            ptype = _PATTERN_TO_TYPE.get(name, name.upper())
            item_level = (
                SensitivityLevel.S3 if name in s3_names else SensitivityLevel.S2
            )
            items.append(
                PIIItem(
                    original_text=val,
                    privacy_type=ptype,
                    level=item_level,
                    start=m.start(),
                    end=m.end(),
                )
            )
            seen_spans.add(span)

    items.sort(key=lambda x: len(x.original_text), reverse=True)
    return items


def pseudonymize_text(
    content: str,
    store: PseudonymStore,
    level: SensitivityLevel,
) -> PseudonymizeResult:
    """Replace PII at *level* in *content* with typed pseudonyms via *store*.

    Only replaces PII matching the specified sensitivity level,
    respecting the per-level action configured in PrivacyPolicy.

    Returns a ``PseudonymizeResult`` with the pseudonymized text, count,
    and list of detected items.
    """
    if not content:
        return PseudonymizeResult(text=content)

    items = _extract_pii_items(content, level)
    if not items:
        return PseudonymizeResult(text=content)

    result = content
    count = 0
    for item in items:
        pseudonym = store.get_or_create(
            item.original_text,
            item.privacy_type,
            item.level.value,
        )
        result = result.replace(item.original_text, pseudonym)
        count += 1

    return PseudonymizeResult(text=result, count=count, items=items)


class PseudonymRestorer:
    """Streaming-safe pseudonym → original text restorer.

    Handles the case where a pseudonym token like ``<PHONE_NUMBER_1>``
    may be split across multiple streaming chunks by buffering partial
    tokens until the closing ``>`` is received.

    Usage::

        restorer = PseudonymRestorer(store)
        for chunk in stream:
            restored = restorer.process(chunk)
            yield restored
        # flush any remaining buffer
        final = restorer.flush()
        if final:
            yield final
    """

    __slots__ = ("_buffer", "_store")

    _MAX_BUFFER = 50

    def __init__(self, store: PseudonymStore) -> None:
        self._store = store
        self._buffer = ""

    def process(self, chunk: str) -> str:
        """Process a streaming chunk, returning restored text.

        Buffered partial pseudonym tokens are held until they complete
        or exceed the max buffer length.
        """
        text = self._buffer + chunk
        self._buffer = ""

        lt_idx = text.rfind("<")
        if lt_idx != -1 and ">" not in text[lt_idx:]:
            tail = text[lt_idx:]
            if len(tail) <= self._MAX_BUFFER:
                self._buffer = tail
                text = text[:lt_idx]

        return self._store.resolve_all(text)

    def flush(self) -> str:
        """Flush any remaining buffer content."""
        if self._buffer:
            result = self._store.resolve_all(self._buffer)
            self._buffer = ""
            return result
        return ""
