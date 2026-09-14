"""Heading fusion and in-place placement for PDF page text.

[INPUT]
- NumberingHeading candidates (pdf_numbering) and font-derived PDFHeading values
- Page text produced by the parser

[OUTPUT]
- build_numbering_cues: per-page visual titles used as numbering cues
- fuse_headings: unified heading list with single precedence rules
- insert_headings_into_page_text: headings placed at their original line,
  unfound headings hoisted to the page top (legacy-safe fallback)

[POS]
Composes all heading sources and renders them into page text without
duplicating the clause line, so downstream chunking keeps correct section
attribution.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from myrm_agent_harness.toolkits.file_parsers.base import PDFHeading
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_numbering import (
    NumberingHeading,
    normalize_heading_title,
)

_EXISTING_MARKER_RE = re.compile(r"^#+\s*")


def build_numbering_cues(font_headings: Sequence[PDFHeading]) -> dict[int, frozenset[str]]:
    """Group visual heading titles per page for numbering-family cue matching."""
    cues: dict[int, set[str]] = {}
    for heading in font_headings:
        cues.setdefault(heading.page_num, set()).add(normalize_heading_title(heading.title))
    return {page: frozenset(titles) for page, titles in cues.items()}


def fuse_headings(
    numbering: Sequence[NumberingHeading],
    font_headings: Sequence[PDFHeading],
) -> list[PDFHeading]:
    """Merge numbering and font candidates; numbering level wins on collision."""
    fused: list[PDFHeading] = []
    seen: set[tuple[int, str]] = set()

    for hit in numbering:
        key = (hit.page_num, normalize_heading_title(hit.title))
        seen.add(key)
        fused.append(PDFHeading(level=hit.level, title=hit.title, page_num=hit.page_num))

    for heading in font_headings:
        key = (heading.page_num, normalize_heading_title(heading.title))
        if key in seen:
            continue
        seen.add(key)
        fused.append(heading)

    return fused


def insert_headings_into_page_text(page_text: str, headings: Sequence[PDFHeading]) -> str:
    """Insert Markdown heading markers at each heading's original line.

    Headings that cannot be matched to a body line are hoisted to the page top
    (previous behaviour), so callers never lose a heading or corrupt the body.
    """
    if not headings:
        return page_text
    if not page_text:
        return _hoisted_only(headings).rstrip("\n")

    lines = page_text.split("\n")
    consumed: set[int] = set()
    resolved: list[tuple[int, PDFHeading]] = []
    unresolved: list[PDFHeading] = []

    for heading in headings:
        normalized = normalize_heading_title(heading.title)
        line_index = _find_line(lines, normalized, consumed)
        if line_index is None:
            unresolved.append(heading)
            continue
        consumed.add(line_index)
        if lines[line_index].lstrip().startswith("#"):
            continue
        resolved.append((line_index, heading))

    for line_index, heading in sorted(resolved, key=lambda item: item[0]):
        lines[line_index] = f"{'#' * heading.level} {lines[line_index].lstrip()}"

    hoisted = _hoisted_only(unresolved)
    return hoisted + "\n".join(lines)


def _find_line(lines: Sequence[str], normalized_title: str, consumed: set[int]) -> int | None:
    """Locate the first unconsumed body line matching a heading title."""
    if not normalized_title:
        return None
    prefix_match: int | None = None
    for index, line in enumerate(lines):
        if index in consumed:
            continue
        normalized_line = normalize_heading_title(_EXISTING_MARKER_RE.sub("", line))
        if not normalized_line:
            continue
        if normalized_line == normalized_title:
            return index
        if prefix_match is None and len(normalized_title) >= 2 and normalized_line.startswith(normalized_title):
            prefix_match = index
    return prefix_match


def _hoisted_only(headings: Sequence[PDFHeading]) -> str:
    """Render headings as top-of-page Markdown lines."""
    if not headings:
        return ""
    rendered = [f"{'#' * heading.level} {heading.title}" for heading in headings]
    return "\n".join(rendered) + "\n"
