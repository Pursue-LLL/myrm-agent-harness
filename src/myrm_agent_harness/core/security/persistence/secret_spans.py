"""Secret spans for persistence: locate labeled secret values and redact spans from a text.

[INPUT]
- core.security.assignment_sweep::find_assignment_matches / AssignmentKeyFamily (POS: single definition of a
  non-benign `<sensitive key><delimiter><value>` assignment, with the value span.)
- core.security.detection.password_heuristic::secret_value_span (POS: shared value rules.)

[OUTPUT]
- find_assignment_secret_spans: spans of the values assigned to password/api_key/secret/token-style keys.
- redact_spans: replace (possibly overlapping) spans by the redaction marker, leaving every other character intact.

[POS]
Position-based redaction primitives for the persistence scan. Redacting by span replaces exactly the located secret
at the located place, where replacing a token text would also hit every unrelated occurrence of that text.
"""

from __future__ import annotations

from collections.abc import Iterable

from myrm_agent_harness.core.security.assignment_sweep import AssignmentKeyFamily, find_assignment_matches
from myrm_agent_harness.core.security.detection.password_heuristic import Span, secret_value_span

REDACTION_MARKER = "[REDACTED]"
_QUOTES = "\"'`"


def _value_end(line: str, start: int, end: int) -> int:
    """Where the secret ends: the closing quote of a quoted value (passphrases contain spaces), else the last ASCII
    character, so prose glued to a value without whitespace ("密码：abc123，请勿转发") stays out of the span."""
    if start > 0 and line[start - 1] in _QUOTES:
        closing = line.find(line[start - 1], start)
        if closing != -1:
            return closing
    for index in range(start, end):
        if not line[index].isascii():
            return index
    return end


def find_assignment_secret_spans(text: str) -> list[Span]:
    """Value spans of plausible secrets assigned to a sensitive key (``password=x``, ``"api_key": "x"``, ``密码：x``)."""
    spans: list[Span] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        for match in find_assignment_matches(line):
            span = secret_value_span(
                line,
                match.value_start,
                _value_end(line, match.value_start, match.value_end),
                allow_letters_only=match.family is AssignmentKeyFamily.PASSWORD,
            )
            if span is not None:
                spans.append((offset + span[0], offset + span[1]))
        offset += len(line)
    return spans


def redact_spans(text: str, spans: Iterable[Span]) -> str:
    """Replace every span with the redaction marker; overlapping and adjacent spans collapse into one marker."""
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    pieces: list[str] = []
    cursor = 0
    for start, end in merged:
        pieces.append(text[cursor:start])
        pieces.append(REDACTION_MARKER)
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)
