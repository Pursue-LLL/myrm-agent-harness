"""Font-based heading detection for PDF files without bookmarks.

Analyzes font size distribution across sampled pages to infer heading hierarchy.
When a PDF has no bookmarks/outlines, this module provides a fallback mechanism
to detect structural headings based on font metrics.

[INPUT]
- pdfplumber.PDF: An opened pdfplumber PDF object

[OUTPUT]
- detect_headings_by_font(): Returns list of detected headings with level, title, and page number

[POS]
Font-based heading detection for PDFs without bookmarks. Uses statistical font
size analysis with page header/footer deduplication.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pdfplumber

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FontHeadingConfig:
    """Configuration for font-based heading detection."""

    min_delta: float = 1.5
    max_levels: int = 4
    sample_interval: int = 5
    header_threshold: float = 0.3
    min_title_length: int = 2
    max_title_length: int = 120


@dataclass(frozen=True, slots=True)
class DetectedHeading:
    """A heading detected via font size analysis."""

    level: int
    title: str
    page_num: int


def detect_headings_by_font(
    pdf: pdfplumber.PDF,
    config: FontHeadingConfig | None = None,
) -> list[dict[str, int | str | None]]:
    """Detect headings by analyzing font size distribution.

    Algorithm:
    1. Sample font sizes from every N-th page to determine body font size
    2. Identify heading font sizes (larger than body by min_delta)
    3. Extract heading text from all pages matching heading sizes
    4. Deduplicate: filter text appearing on >30% of pages (page headers/footers)

    Returns list compatible with bookmark format:
        [{"level": int, "title": str, "page_num": int}]
    """
    cfg = config or FontHeadingConfig()

    try:
        size_to_level = _compute_heading_sizes(pdf, cfg)
        if not size_to_level:
            return []

        headings = _extract_heading_text(pdf, size_to_level, cfg)
        headings = _deduplicate_headers(headings, len(pdf.pages), cfg.header_threshold)

        logger.info(
            "Font heading detection: %d headings found across %d pages",
            len(headings),
            len(pdf.pages),
        )
        return [
            {"level": h.level, "title": h.title, "page_num": h.page_num}
            for h in headings
        ]

    except Exception as e:
        logger.warning("Font heading detection failed: %s", e)
        return []


def _compute_heading_sizes(
    pdf: pdfplumber.PDF,
    cfg: FontHeadingConfig,
) -> dict[float, int]:
    """Sample font sizes and compute heading size → level mapping."""
    size_counter: Counter[float] = Counter()

    sample_pages = pdf.pages[:: cfg.sample_interval]
    for page in sample_pages:
        for char in page.chars:
            if char.get("text", "").strip():
                rounded = round(char["size"] * 2) / 2
                size_counter[rounded] += 1

    if not size_counter:
        return {}

    body_size = size_counter.most_common(1)[0][0]

    heading_sizes = sorted(
        [
            s
            for s, count in size_counter.items()
            if s >= body_size + cfg.min_delta
            and count < size_counter[body_size] * 0.5
        ],
        reverse=True,
    )

    heading_sizes = heading_sizes[: cfg.max_levels]
    if not heading_sizes:
        logger.debug(
            "Font analysis: body_size=%.1fpt, no heading sizes found", body_size
        )
        return {}

    size_to_level = {s: i + 1 for i, s in enumerate(heading_sizes)}
    logger.debug(
        "Font analysis: body_size=%.1fpt, heading_sizes=%s",
        body_size,
        heading_sizes,
    )
    return size_to_level


_NOISE_PATTERN = re.compile(r"^[\d\s.·…\-–—]+$")


def _extract_heading_text(
    pdf: pdfplumber.PDF,
    size_to_level: dict[float, int],
    cfg: FontHeadingConfig,
) -> list[DetectedHeading]:
    """Extract heading text from all pages based on detected heading sizes."""
    headings: list[DetectedHeading] = []

    for page in pdf.pages:
        page_num = page.page_number
        chars = sorted(page.chars, key=lambda c: (c["top"], c["x0"]))

        current_line_chars: list[dict] = []
        current_top: float | None = None

        for char in chars:
            rounded_size = round(char["size"] * 2) / 2
            if rounded_size not in size_to_level:
                _flush_line(current_line_chars, page_num, size_to_level, cfg, headings)
                current_line_chars = []
                current_top = None
                continue

            if current_top is not None and abs(char["top"] - current_top) > 2:
                _flush_line(current_line_chars, page_num, size_to_level, cfg, headings)
                current_line_chars = []

            current_line_chars.append(char)
            current_top = char["top"]

        _flush_line(current_line_chars, page_num, size_to_level, cfg, headings)

    return headings


def _flush_line(
    chars: list[dict],
    page_num: int,
    size_to_level: dict[float, int],
    cfg: FontHeadingConfig,
    output: list[DetectedHeading],
) -> None:
    """Flush accumulated chars as a heading if they meet criteria."""
    if not chars:
        return

    title = "".join(c.get("text", "") for c in chars).strip()

    if len(title) < cfg.min_title_length:
        return
    if len(title) > cfg.max_title_length:
        return
    if title.isdigit():
        return
    if _NOISE_PATTERN.match(title):
        return

    size = round(chars[0]["size"] * 2) / 2
    level = size_to_level.get(size)
    if level is None:
        return

    output.append(DetectedHeading(level=level, title=title, page_num=page_num))


def _deduplicate_headers(
    headings: list[DetectedHeading],
    total_pages: int,
    threshold: float,
) -> list[DetectedHeading]:
    """Remove repeated text appearing on too many pages (likely page headers/footers).

    Only applies when total_pages >= 4 (dedup is meaningless for short documents).
    """
    if total_pages < 4:
        return headings

    title_page_count: Counter[str] = Counter(h.title for h in headings)
    header_titles = {
        t for t, c in title_page_count.items() if c > total_pages * threshold
    }

    if header_titles:
        logger.debug(
            "Filtered %d header/footer titles: %s",
            len(header_titles),
            list(header_titles)[:5],
        )

    return [h for h in headings if h.title not in header_titles]
