"""Custom keyword and pattern rules: where a user-defined term sits in a text.

Classification asks whether a rule hits, redaction replaces the spans and pseudonymization swaps them for tags, all
three read the spans found here, so a term that is detected is a term that is masked.

A keyword matches in any case, at every occurrence. Where its first or last character belongs to a script that
separates words with spaces (ASCII letters and digits, underscore, Latin, Greek, Cyrillic) the match must not run into
a neighbouring word of that script: ``pin`` is not in ``spinners`` and ``pass`` is not in ``password123``. Where the
edge is Chinese, Japanese or Korean text or punctuation (``.env``) there is no boundary to respect, so ``凤凰计划``
matches inside a sentence and ``project`` matches between Chinese characters. A pattern is a regular expression applied
in any case; an invalid one never matches, and a match of zero length is not a span. A span that touches a marker an
earlier redaction or pseudonymization wrote (``[PII:phone]``, ``<PHONE_NUMBER_1>``) is dropped, so applying the same
rules to their own output changes nothing.

[INPUT]
- core.security.detection.pseudonym_store::_PSEUDONYM_RE (POS: Local SQLite store for reversible PII pseudonymization. Maps original_text to typed placeholders (<TYPE_N>) with cross-session persistence.)
- core.security.types::PrivacyPolicy, SensitivityLevel (POS: Foundation layer of the security type hierarchy. All other security modules import from here; this module imports from none of them.)

[OUTPUT]
- CustomRules / NO_CUSTOM_RULES: the keywords and patterns of one or more sensitivity levels
- custom_rules: the rules a policy lists for the given levels, blank entries dropped
- CustomSpan: one hit (start, end, kind, rule)
- find_custom_spans: the non-overlapping spans of a text, leftmost and longest first
- first_custom_span: the first hit in rule order, for callers that only ask whether a rule applies

[POS]
Single definition of custom-term matching for the privacy policy: the PII classifier, the redactor and the pseudonymizer
share it, so detection and masking never disagree about what a user's keyword or pattern covers.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from myrm_agent_harness.core.security.detection.pseudonym_store import _PSEUDONYM_RE
from myrm_agent_harness.core.security.types import PrivacyPolicy, SensitivityLevel

# Characters of the scripts that separate words with spaces: a keyword edge in one of them has a word boundary.
_SPACED_WORD = "0-9A-Za-z_\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f\u0370-\u03ff\u0400-\u04ff"
_SPACED_WORD_CHAR = re.compile(f"[{_SPACED_WORD}]")

# What the redactor and the leak detector write ("[REDACTED] [PII:custom]", "[REDACTED:key]") and the pseudonym tags.
_MARKER_RE = re.compile(rf"\[(?:REDACTED|PII)[^\]\n]{{0,40}}\]|{_PSEUDONYM_RE.pattern}")

SpanKind = Literal["keyword", "pattern"]


@dataclass(frozen=True, slots=True)
class CustomRules:
    """The keywords and regular-expression patterns to look for."""

    keywords: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.keywords or self.patterns)


NO_CUSTOM_RULES = CustomRules()


@dataclass(frozen=True, slots=True)
class CustomSpan:
    """A hit of ``rule`` (a keyword or a pattern, as configured) at ``text[start:end]``."""

    start: int
    end: int
    kind: SpanKind
    rule: str


def custom_rules(policy: PrivacyPolicy, *levels: SensitivityLevel) -> CustomRules:
    """The rules *policy* lists for *levels*; a blank keyword or pattern would match everywhere, so it is dropped."""
    keywords: list[str] = []
    patterns: list[str] = []
    for level in levels:
        if level == SensitivityLevel.S2:
            keywords.extend(policy.custom_keywords_s2)
            patterns.extend(policy.custom_patterns_s2)
        elif level == SensitivityLevel.S3:
            keywords.extend(policy.custom_keywords_s3)
            patterns.extend(policy.custom_patterns_s3)
    return CustomRules(
        keywords=tuple(dict.fromkeys(word for word in (keyword.strip() for keyword in keywords) if word)),
        patterns=tuple(dict.fromkeys(pattern for pattern in patterns if pattern.strip())),
    )


def find_custom_spans(content: str, rules: CustomRules) -> list[CustomSpan]:
    """Every span of *content* the rules cover, sorted, none overlapping; of two overlapping hits the longer wins."""
    if rules.is_empty:
        return []
    spans: list[CustomSpan] = []
    cursor = 0
    for span in sorted(_live_spans(content, rules), key=lambda found: (found.start, found.start - found.end)):
        if span.start >= cursor:
            spans.append(span)
            cursor = span.end
    return spans


def first_custom_span(content: str, rules: CustomRules) -> CustomSpan | None:
    """The first hit in rule order (keywords, then patterns), or None; stops at the first hit."""
    return next(_live_spans(content, rules), None)


@lru_cache(maxsize=512)
def _keyword_regex(keyword: str) -> re.Pattern[str]:
    head = f"(?<![{_SPACED_WORD}])" if _SPACED_WORD_CHAR.match(keyword[0]) else ""
    tail = f"(?![{_SPACED_WORD}])" if _SPACED_WORD_CHAR.match(keyword[-1]) else ""
    return re.compile(f"{head}{re.escape(keyword)}{tail}", re.IGNORECASE)


@lru_cache(maxsize=512)
def _pattern_regex(pattern: str) -> re.Pattern[str] | None:
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return None


def _raw_spans(content: str, rules: CustomRules) -> Iterator[CustomSpan]:
    for keyword in rules.keywords:
        if keyword:
            for match in _keyword_regex(keyword).finditer(content):
                yield CustomSpan(match.start(), match.end(), "keyword", keyword)
    for pattern in rules.patterns:
        compiled = _pattern_regex(pattern)
        if compiled is not None:
            for match in compiled.finditer(content):
                if match.end() > match.start():
                    yield CustomSpan(match.start(), match.end(), "pattern", pattern)


def _live_spans(content: str, rules: CustomRules) -> Iterator[CustomSpan]:
    """The raw spans that do not touch a marker; the markers are located once, and only when a rule hits."""
    marker_starts: list[int] | None = None
    marker_ends: list[int] = []
    for span in _raw_spans(content, rules):
        if marker_starts is None:
            bounds = [marker.span() for marker in _MARKER_RE.finditer(content)]
            marker_starts = [start for start, _ in bounds]
            marker_ends = [end for _, end in bounds]
        if not _touches_marker(span, marker_starts, marker_ends):
            yield span


def _touches_marker(span: CustomSpan, starts: list[int], ends: list[int]) -> bool:
    """Whether *span* overlaps one of the markers, which are sorted and disjoint."""
    before = bisect_right(starts, span.start) - 1
    if before >= 0 and ends[before] > span.start:
        return True
    return before + 1 < len(starts) and starts[before + 1] < span.end
