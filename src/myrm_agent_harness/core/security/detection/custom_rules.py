"""Custom keyword and pattern rules: where a user-defined term sits in a text.

Classification asks whether a rule hits, redaction replaces the spans and pseudonymization swaps them for tags, all
three read the spans found here, so a term that is detected is a term that is masked.

A keyword matches in any case, at every occurrence. Where its first or last character belongs to a script that
separates words with spaces (ASCII letters and digits, underscore, Latin, Greek, Cyrillic) the match must not run into
a neighbouring word of that script: ``pin`` is not in ``spinners`` and ``pass`` is not in ``password123``. Where the
edge is Chinese, Japanese or Korean text or punctuation (``.env``) there is no boundary to respect, so ``凤凰计划``
matches inside a sentence and ``project`` matches between Chinese characters. A pattern is a regular expression applied
in any case, in the syntax of the ``regex`` package (everything ``re`` accepts, plus Unicode property classes for
Chinese text and ``(?<name>...)`` groups); one that does not compile, or whose counted repeats would take more memory
to build than a pattern is worth (``a{99999999}``), never matches (``ineffective_patterns`` names them), and a match of
zero length is not a span. A pattern that cannot finish a text within the time budget (a
backtracking blow-up would otherwise keep a worker and a CPU core busy for minutes) counts the whole text as its hit,
so the text is masked rather than let through. A span that touches a marker an earlier redaction or pseudonymization wrote
(``[PII:phone]``, ``<PHONE_NUMBER_1>``) is dropped, so applying the same rules to their own output changes nothing;
the whole-text hit of a timed-out pattern is kept, as there is no telling which part of the text it would have matched.

[INPUT]
- core.security.detection.pseudonym_store::_PSEUDONYM_RE (POS: Local SQLite store for reversible PII pseudonymization. Maps original_text to typed placeholders (<TYPE_N>) with cross-session persistence.)
- core.security.types::PrivacyPolicy, SensitivityLevel (POS: Foundation layer of the security type hierarchy. All other security modules import from here; this module imports from none of them.)

[OUTPUT]
- CustomRules / NO_CUSTOM_RULES: the keywords and patterns of one or more sensitivity levels
- custom_rules: the rules a policy lists for the given levels, blank entries dropped
- CustomSpan: one hit (start, end, kind, rule, timed_out)
- find_custom_spans: the non-overlapping spans of a text, leftmost and longest first
- first_custom_span: the first hit in rule order, for callers that only ask whether a rule applies
- ineffective_patterns: the patterns that cannot be used (they do not compile or are too large to build) and so protect nothing

[POS]
Single definition of custom-term matching for the privacy policy: the PII classifier, the redactor and the pseudonymizer
share it, so detection and masking never disagree about what a user's keyword or pattern covers.
"""

from __future__ import annotations

import logging
from bisect import bisect_right
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import regex

from myrm_agent_harness.core.security.detection.pseudonym_store import _PSEUDONYM_RE
from myrm_agent_harness.core.security.types import PrivacyPolicy, SensitivityLevel

logger = logging.getLogger(__name__)

# Time one pattern may take to scan one text. A legitimate pattern needs milliseconds (a 5 MB text takes ~0.15 s);
# a backtracking blow-up has no end, so the budget bounds how long it keeps one worker and one CPU core busy.
_PATTERN_TIMEOUT_SECONDS = 1.0

# ``regex`` lays out every copy of a counted repeat when it compiles (``a{10000000}`` takes 2.7 GB where ``re`` stores the
# count), and the repeats of one pattern multiply (``(?:a{1000}){1000}`` is a million atoms, ~300 MB). A pattern whose
# repeats add more atoms than this to the ones it spells out is refused; real patterns add tens, and the limit keeps
# the memory of one compile to a few megabytes.
_MAX_REPEAT_ATOMS = 10_000
_COUNTED_REPEAT = regex.compile(r"\{(\d{0,9})(?:,\d{0,9})?\}")
_REPEAT_SYNTAX = regex.compile(r"[\\\[(){]")  # the characters the repeat scan must stop at; any other is one atom

# Characters of the scripts that separate words with spaces: a keyword edge in one of them has a word boundary.
_SPACED_WORD = "0-9A-Za-z_\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f\u0370-\u03ff\u0400-\u04ff"
_SPACED_WORD_CHAR = regex.compile(f"[{_SPACED_WORD}]")

# What the redactor and the leak detector write ("[REDACTED] [PII:custom]", "[REDACTED:key]") and the pseudonym tags.
_MARKER_RE = regex.compile(rf"\[(?:REDACTED|PII)[^\]\n]{{0,40}}\]|{_PSEUDONYM_RE.pattern}")

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
    """A hit of ``rule`` (a keyword or a pattern, as configured) at ``text[start:end]``.

    ``timed_out`` marks the whole-text hit of a pattern that could not finish scanning within the time budget.
    """

    start: int
    end: int
    kind: SpanKind
    rule: str
    timed_out: bool = False


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


def ineffective_patterns(patterns: Iterable[str]) -> tuple[str, ...]:
    """The distinct *patterns* that cannot be used, as they do not compile or are too large to build: they protect
    nothing, and the user should be told so."""
    return tuple(pattern for pattern in dict.fromkeys(patterns) if _pattern_regex(pattern) is None)


@lru_cache(maxsize=512)
def _keyword_regex(keyword: str) -> regex.Pattern[str]:
    head = f"(?<![{_SPACED_WORD}])" if _SPACED_WORD_CHAR.match(keyword[0]) else ""
    tail = f"(?![{_SPACED_WORD}])" if _SPACED_WORD_CHAR.match(keyword[-1]) else ""
    return regex.compile(f"{head}{regex.escape(keyword)}{tail}", regex.IGNORECASE)


@lru_cache(maxsize=512)
def _pattern_regex(pattern: str) -> regex.Pattern[str] | None:
    # A pattern the engine rejects as malformed, too large to build or nested too deep never matches; none may raise.
    if _repeat_atoms(pattern) > _MAX_REPEAT_ATOMS:
        return None
    try:
        return regex.compile(pattern, regex.IGNORECASE)
    except (regex.error, OverflowError, RecursionError):
        return None


def _repeat_atoms(pattern: str) -> int:
    """How many atoms the counted repeats of *pattern* add to the ones it spells out; a group repeated n times is n copies.

    Only the least number of copies of a repeat matters: ``{n}``, ``{n,}`` and ``{n,m}`` lay out ``n`` of them (at least
    one), ``?``, ``*``, ``+`` and ``{,m}`` one. The scan reads just enough of the syntax to know what a repeat applies
    to, errs on the high side (a group header such as ``?:`` counts as atoms) and stops once the budget is spent.
    """
    added = 0
    groups = [0]  # atoms of the groups still open, the innermost last
    last = 0  # atoms of the item a following repeat applies to
    position = 0
    while position < len(pattern):
        syntax = _REPEAT_SYNTAX.search(pattern, position)
        plain_end = syntax.start() if syntax else len(pattern)
        if plain_end > position:
            groups[-1] += plain_end - position
            last = 1
            position = plain_end
            continue
        char = pattern[position]
        if char == "(":
            groups.append(0)
            position += 1
        elif char == "{" and (repeat := _COUNTED_REPEAT.match(pattern, position)):
            extra = last * (max(int(repeat[1] or 0), 1) - 1)
            groups[-1] += extra
            last += extra
            added += extra
            position = repeat.end()
            if added > _MAX_REPEAT_ATOMS:
                break
        else:
            if char == ")":
                last = groups.pop() if len(groups) > 1 else 0
                position += 1
            elif char == "[":
                last = 1
                position = _class_end(pattern, position)
            else:
                last = 1
                position += 2 if char == "\\" else 1
            groups[-1] += last
    return added


def _class_end(pattern: str, start: int) -> int:
    """The index just past the character class opening at *start*; the pattern's end when it never closes."""
    position = start + 1
    if pattern.startswith("^", position):
        position += 1
    if pattern.startswith("]", position):  # a leading "]" is a member, not the end
        position += 1
    while position < len(pattern) and pattern[position] != "]":
        position += 2 if pattern[position] == "\\" else 1
    return position + 1


def _raw_spans(content: str, rules: CustomRules) -> Iterator[CustomSpan]:
    for keyword in rules.keywords:
        if keyword:
            for match in _keyword_regex(keyword).finditer(content):
                yield CustomSpan(match.start(), match.end(), "keyword", keyword)
    for index, pattern in enumerate(rules.patterns):
        compiled = _pattern_regex(pattern)
        if compiled is None:
            continue
        try:
            for match in compiled.finditer(content, timeout=_PATTERN_TIMEOUT_SECONDS):
                if match.end() > match.start():
                    yield CustomSpan(match.start(), match.end(), "pattern", pattern)
        except TimeoutError:
            logger.warning(
                "[Privacy] custom pattern #%d did not finish a %d-character text in %.1fs; the whole text counts as its hit",
                index + 1,
                len(content),
                _PATTERN_TIMEOUT_SECONDS,
            )
            yield CustomSpan(0, len(content), "pattern", pattern, timed_out=True)
            return


def _live_spans(content: str, rules: CustomRules) -> Iterator[CustomSpan]:
    """The raw spans that do not touch a marker; the markers are located once, and only when a rule hits."""
    marker_starts: list[int] | None = None
    marker_ends: list[int] = []
    for span in _raw_spans(content, rules):
        if span.timed_out:
            yield span
            continue
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
