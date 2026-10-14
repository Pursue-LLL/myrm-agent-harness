"""Card-number detector anchored to the words that introduce one ("银行卡号 …", "card number is …").

The prefix table in pii_classifier knows the major networks and checks the Luhn digit. A Maestro, Mir, RuPay or Troy
number matches no prefix, and a number with a typo fails the check, yet the text leaves no doubt about what the digits
are. This is the complement: any plausible card-number shape right after a card keyword.

[INPUT]
- core.security.detection.secret_value::Span (POS: shared value rules, reference rejection, markup masking.)

[OUTPUT]
- find_card_number_spans(): sorted (start, end) spans of the card numbers a text introduces as a card, the number
  itself and never the keyword or the expiry date and CVV typed after it
- find_card_shaped_spans(): (start, end) spans, sorted by start, of every digit run shaped like a card number, introduced
  or not; a grouped number is also found from each later group, so a card typed right after another group of four is
  not hidden behind it

[POS]
Keyword-anchored detector for card numbers outside the network prefix table or with a typo in them. The keyword is
the evidence, so a bare "card" or a digit run no keyword introduces yields nothing. The classifier, the redactor and
the pseudonymizer share it so they never disagree about which digits are a card. The shape alone proves nothing (an
order number has one too); a caller that must not miss a card adds its own evidence, such as the Luhn check.
"""

from __future__ import annotations

import re

from myrm_agent_harness.core.security.detection.secret_value import Span

# "card" alone is everyday vocabulary (SIM card, member card, "card 3 of 12"); only these name a payment card. An
# English keyword does not continue a word ("discard number").
_CARD_KEYWORD = (
    r"(?:银行卡|信用卡|储蓄卡|借记卡|卡号|"
    r"(?<![A-Za-z])(?:bank card|credit card|debit card|card number|card no\b\.?))"
)

# Thirteen to nineteen digits in one run, or typed with the same hyphen or space in groups of 4-4-4-4, 4-6-5 (Amex) or
# 4-6-4 (14-digit Diners). Shaped rather than "any digits and separators", so the expiry date or CVV typed after the
# number ("... 8453 12/28") is not swallowed by it.
_CARD_NUMBER = (
    r"(?<!\d)(?:"
    r"\d{13,19}"
    r"|\d{4}(?P<sep16>[- ])\d{4}(?P=sep16)\d{4}(?P=sep16)\d{4}"
    r"|\d{4}(?P<sep15>[- ])\d{6}(?P=sep15)\d{4,5}"
    r")(?!\d)"
)

# Looked for at every start, overlapping: in "2026 5018 5260 1815 9080" the card is the last four groups, and a match
# from the leftmost start would take the first four.
_CARD_SHAPE_RE = re.compile(rf"(?=(?P<shape>{_CARD_NUMBER}))")

# A few words between keyword and number ("card number is", "bank card (Maestro):"), never a digit or a line break.
_CARD_CONTEXT_RE = re.compile(rf"{_CARD_KEYWORD}[^\d\n]{{0,16}}(?P<number>{_CARD_NUMBER})", re.IGNORECASE)


def find_card_number_spans(text: str) -> list[Span]:
    """Spans of the card numbers *text* introduces with a card keyword, in text order."""
    # Every keyword holds "卡" or "card". Most texts hold neither, and looking for them is far cheaper than trying the
    # keyword alternation at every position of the text.
    if "卡" not in text and "card" not in text.lower():
        return []
    return [match.span("number") for match in _CARD_CONTEXT_RE.finditer(text)]


def find_card_shaped_spans(text: str) -> list[Span]:
    """Spans of every digit run in *text* shaped like a card number, sorted by start; they may overlap."""
    return [match.span("shape") for match in _CARD_SHAPE_RE.finditer(text)]
