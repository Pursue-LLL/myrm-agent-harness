"""Clause-numbering heading detection for bookmark-less PDFs.

[INPUT]
- page_texts: per-page extracted text (page 1 first)
- cue_titles: optional per-page titles from visual detection, used to keep
  structural levels for headings that are also visually prominent

[OUTPUT]
- NumberingHeading: (page_num, level, title, line_index)
- detect_numbering_headings: guarded detection with document-level level mapping
- filter_repeated_titles: drops running page headers/footers from candidates
- normalize_heading_title: shared title normalisation

[POS]
Clause-numbering heading detection for bookmark-less PDFs with precision-first
guards (第X章/节/条, 一、, （一）, 1.1.1, 1., ①). Detection failure degrades to
"no headings" and never corrupts the extracted text.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_CN_NUMERALS = "一二三四五六七八九十百千"

_CHAPTER_RE = re.compile(rf"^第\s*([0-9]+|[{_CN_NUMERALS}]+)\s*(?:章|篇|部分)\s*[·:：\-—、.]?\s*(.*)$")
_SECTION_RE = re.compile(rf"^第\s*([0-9]+|[{_CN_NUMERALS}]+)\s*节\s*[·:：\-—、.]?\s*(.*)$")
_ARTICLE_RE = re.compile(rf"^第\s*([0-9]+|[{_CN_NUMERALS}]+)\s*条\s*[·:：\-—、.]?\s*(.*)$")
_CN_ORDINAL_RE = re.compile(rf"^([{_CN_NUMERALS}]+)\s*[、.．]\s*(.*)$")
_CN_PAREN_RE = re.compile(rf"^[（(]\s*([{_CN_NUMERALS}0-9]+)\s*[)）]\s*(.*)$")
_NUM_MULTI_RE = re.compile(r"^(\d+(?:\.\d+){1,5})(.*)$")
_NUM_SINGLE_RE = re.compile(r"^(\d{1,3})\s*[、.．]\s*(.*)$")
_CIRCLED_RE = re.compile(r"^([①②③④⑤⑥⑦⑧⑨⑩])\s*(.*)$")

_LEADER_RE = re.compile(r"\.{3,}|·{2,}|。{3,}|\u2026")
_TRAILING_PAGE_RE = re.compile(r"[ \t\u3000]+\d{1,4}\s*$")
_SENTENCE_MARK_RE = re.compile(r"[。；;！？!?]")
_YEARLIKE_RE = re.compile(r"^(?:19|20)\d{2}\s*(?:年|[.．]\d{1,2})")
_EXTRA_MARKER_RE = re.compile(
    rf"第\s*[0-9{_CN_NUMERALS}]+\s*(?:章|节|条)|[（(]\s*[0-9{_CN_NUMERALS}]+\s*[)）]|[①-⑩]|[{_CN_NUMERALS}]{{1,3}}[、.．]"
)
_WHITESPACE_RE = re.compile(r"\s+")

# Standalone table-of-contents markers: TOC entries echo real headings and must
# not be injected as headings (they carry the TOC page instead of the section).
_TOC_MARKERS = frozenset({"目录", "目次", "contents", "tableofcontents", "toc"})


@dataclass(frozen=True, slots=True)
class NumberingHeadingConfig:
    """Guard thresholds; precision-first defaults."""

    max_line_chars: int = 60
    min_title_chars: int = 1
    max_headings_per_page: int = 6
    repeat_page_ratio: float = 0.3
    max_components: int = 5
    max_component_digits: int = 2


@dataclass(frozen=True, slots=True)
class NumberingHeading:
    """A numbering-derived heading candidate (title is the full heading line)."""

    page_num: int
    level: int
    title: str
    line_index: int


@dataclass(frozen=True, slots=True)
class _Family:
    """Numbering family: pattern, hierarchy rank, and single-level trust flag."""

    name: str
    rank: int
    pattern: re.Pattern[str]
    single_level: bool = False


@dataclass(frozen=True, slots=True)
class _Candidate:
    """Accepted candidate carrying its structural identity for level mapping."""

    page_num: int
    line_index: int
    title: str
    family: str
    rank: int
    depth: int


_FAMILIES: tuple[_Family, ...] = (
    _Family("cn_chapter", 1, _CHAPTER_RE),
    _Family("cn_section", 2, _SECTION_RE),
    _Family("cn_article", 3, _ARTICLE_RE),
    _Family("cn_ordinal", 4, _CN_ORDINAL_RE),
    _Family("cn_paren", 5, _CN_PAREN_RE),
    _Family("num_multi", 6, _NUM_MULTI_RE),
    _Family("num_single", 7, _NUM_SINGLE_RE, single_level=True),
    _Family("circled", 8, _CIRCLED_RE, single_level=True),
)
_SINGLE_LEVEL_NAMES = frozenset(f.name for f in _FAMILIES if f.single_level)


def normalize_heading_title(title: str) -> str:
    """Normalise a heading title for matching (whitespace-insensitive)."""
    return _WHITESPACE_RE.sub("", title).strip()


def detect_numbering_headings(
    page_texts: Sequence[str],
    cue_titles: Mapping[int, frozenset[str]] | None = None,
    config: NumberingHeadingConfig | None = None,
) -> list[NumberingHeading]:
    """Detect hierarchical headings from clause numbering text.

    Args:
        page_texts: page text in page order (index 0 is page 1).
        cue_titles: optional {page_num: normalised titles} from visual
            detection; used to relax the single-level colon guard.
        config: guard thresholds.

    Returns:
        Candidates ordered by page and line, with document-level levels 1-6.
    """
    cfg = config or NumberingHeadingConfig()
    if not page_texts:
        return []

    min_depth = _compute_min_numeric_depth(page_texts, cfg)
    candidates: list[_Candidate] = []
    seen_multi: set[str] = set()
    last_single: int | None = None
    families_seen: set[str] = set()

    for page_index, page_text in enumerate(page_texts):
        page_num = page_index + 1
        page_candidates: list[_Candidate] = []
        cues = cue_titles.get(page_num, frozenset()) if cue_titles else frozenset()

        if _looks_like_toc_page(page_text):
            continue

        for line_index, raw_line in enumerate(page_text.split("\n")):
            line = raw_line.strip()
            if not line:
                continue

            matched = _match_family(line)
            if matched is None:
                continue

            family, token, title = matched
            if not _passes_guards(line, family, title, cues, cfg):
                continue

            if family.name == "num_multi":
                if not _accepts_numeric_depth(token, min_depth, seen_multi, cfg):
                    continue
                seen_multi.add(token)
                depth = token.count(".")
            else:
                if family.name == "num_single":
                    value = int(token)
                    if last_single is not None and value < last_single:
                        continue
                    last_single = value
                depth = 0

            families_seen.add(family.name)
            page_candidates.append(
                _Candidate(
                    page_num=page_num,
                    line_index=line_index,
                    title=line,
                    family=family.name,
                    rank=family.rank,
                    depth=depth,
                )
            )

        candidates.extend(page_candidates[: cfg.max_headings_per_page])

    if not candidates:
        return []

    # Single-level families are list-item prone: trust them only when the
    # document also exposes a richer structural family.
    if families_seen <= _SINGLE_LEVEL_NAMES:
        logger.debug("Numbering headings dropped: only single-level list families present")
        return []

    return _assign_levels(candidates)


def filter_repeated_titles(
    headings: Sequence[NumberingHeading],
    page_count: int,
    threshold: float = 0.3,
) -> list[NumberingHeading]:
    """Drop titles repeated across pages (running headers/footers)."""
    if page_count < 4 or not headings:
        return list(headings)

    titles_per_page: dict[str, set[int]] = {}
    for heading in headings:
        titles_per_page.setdefault(normalize_heading_title(heading.title), set()).add(heading.page_num)

    repeated = {title for title, pages in titles_per_page.items() if len(pages) > page_count * threshold}
    if repeated:
        logger.debug("Numbering headings filtered as running titles: %d", len(repeated))
    return [h for h in headings if normalize_heading_title(h.title) not in repeated]


def _assign_levels(candidates: Sequence[_Candidate]) -> list[NumberingHeading]:
    """Map document structural keys to consecutive levels 1-6."""
    keys = sorted({(candidate.rank, candidate.depth) for candidate in candidates})
    key_to_level = {key: min(index + 1, 6) for index, key in enumerate(keys)}

    leveled: list[NumberingHeading] = []
    for candidate in candidates:
        level = key_to_level[(candidate.rank, candidate.depth)]
        leveled.append(
            NumberingHeading(
                page_num=candidate.page_num,
                level=level,
                title=candidate.title,
                line_index=candidate.line_index,
            )
        )
    return leveled


def _match_family(line: str) -> tuple[_Family, str, str] | None:
    """Match the first applicable numbering family; returns (family, token, title)."""
    for family in _FAMILIES:
        match = family.pattern.match(line)
        if match is None:
            continue
        token = match.group(1)
        if family.name == "num_multi":
            title = _split_numeric_runon(token, match.group(2))
        else:
            title = match.group(2).strip()
        if not title:
            return None
        return family, token, title
    return None


def _split_numeric_runon(token: str, remainder_raw: str) -> str | None:
    """Validate a multi-level numeric token and return the title text.

    Accepts ``1.1 Title``, ``1.1、Title``, ``1.1. Title`` and CJK run-ons such
    as ``1.1概述``; rejects float-like tokens (``3.14159``) via component limits.
    """
    components = token.split(".")
    if len(components) > 5 or any(len(part) > 2 for part in components):
        return None

    remainder = remainder_raw.lstrip()
    if remainder[:1] in "、.．" and len(remainder) > 1:
        remainder = remainder[1:]
    return remainder.strip() or None


def _compute_min_numeric_depth(page_texts: Sequence[str], cfg: NumberingHeadingConfig) -> dict[str, int]:
    """Smallest reliable numeric depth per root (``1.1`` roots when no ``1.``)."""
    min_depth: dict[str, int] = {}
    for page_text in page_texts:
        for raw_line in page_text.split("\n"):
            line = raw_line.strip()
            if not line or _LEADER_RE.search(line):
                continue
            match = _NUM_MULTI_RE.match(line)
            if match is None:
                continue
            token = match.group(1)
            components = token.split(".")
            if len(components) > cfg.max_components or any(len(p) > cfg.max_component_digits for p in components):
                continue
            if not _split_numeric_runon(token, match.group(2)):
                continue
            min_depth[components[0]] = min(min_depth.get(components[0], cfg.max_components), len(components) - 1)
    return min_depth


def _accepts_numeric_depth(
    token: str,
    min_depth: dict[str, int],
    seen: set[str],
    cfg: NumberingHeadingConfig,
) -> bool:
    """Accept top-level tokens and any child whose parent was already seen."""
    components = token.split(".")
    if len(components) > cfg.max_components or any(len(p) > cfg.max_component_digits for p in components):
        return False
    root = components[0]
    depth = len(components) - 1
    if depth == min_depth.get(root, 0):
        return True
    parent = token.rsplit(".", 1)[0]
    return parent in seen


def _looks_like_toc_page(page_text: str) -> bool:
    """True when the page carries a standalone table-of-contents marker."""
    for raw_line in page_text.split("\n"):
        marker = normalize_heading_title(raw_line).lower()
        if marker in _TOC_MARKERS:
            return True
    return False


def _passes_guards(
    line: str,
    family: _Family,
    title: str,
    cues: frozenset[str],
    cfg: NumberingHeadingConfig,
) -> bool:
    """Precision-first line guards shared by all families."""
    if not title or len(title) < cfg.min_title_chars:
        return False
    if len(line) > cfg.max_line_chars:
        return False
    if _LEADER_RE.search(line) or _TRAILING_PAGE_RE.search(line):
        return False
    if _SENTENCE_MARK_RE.search(line):
        return False
    if _YEARLIKE_RE.match(line):
        return False
    if _EXTRA_MARKER_RE.search(title):
        return False
    return not (family.single_level and ("：" in title or ":" in title) and normalize_heading_title(line) not in cues)
