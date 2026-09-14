"""PDF bookmark/outline extraction and page resolution.

[INPUT]
- pdfplumber.PDF: an opened pdfplumber PDF object

[OUTPUT]
- extract_bookmarks: resolved bookmarks as PDFHeading values
- bookmarks_are_degenerate: quality gate for generic exporter titles

[POS]
Bookmark source of the PDF heading pipeline. Owns outline walking and
page-object-id resolution so PDFPlumberParser stays an orchestrator.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.file_parsers.base import PDFHeading

if TYPE_CHECKING:
    from pdfplumber.pdf import PDF

logger = logging.getLogger(__name__)

# Titles emitted by generic exporters (slide decks, scans) that carry no
# document structure. A bookmark set dominated by these must not suppress
# text/font detection, and must not be injected as headings.
_GENERIC_TITLE_RE = re.compile(
    r"^(?:幻灯片|slide|page|untitled|sheet|scan(?:ned)?(?: page)?|第\s*\d+\s*页)\s*[\divxlc一二三四五六七八九十]*$",
    re.IGNORECASE,
)
_DEGENERATE_RATIO = 0.6
_DEGENERATE_MIN_BOOKMARKS = 3


def extract_bookmarks(pdf: PDF) -> list[PDFHeading]:
    """Extract resolved bookmarks from the document outline.

    Returns one PDFHeading per bookmark whose destination resolves to a page;
    unresolved destinations are skipped (they cannot be placed in the text).
    """
    try:
        if not hasattr(pdf, "doc") or not hasattr(pdf.doc, "get_outlines"):
            logger.debug("PDF has no outline/bookmark support")
            return []

        outlines = list(pdf.doc.get_outlines())
        if not outlines:
            logger.debug("PDF has no bookmarks")
            return []

        page_ref_map = _build_page_number_map(pdf)
        headings: list[PDFHeading] = []

        for level, title, dest, _action, _se in outlines:
            if not title or not title.strip():
                continue

            page_num = None
            try:
                if dest and len(dest) > 0:
                    page_num = _resolve_bookmark_page(dest[0], page_ref_map, len(pdf.pages))
            except Exception as e:
                logger.debug(f"Failed to resolve bookmark '{title}': {e}")

            if page_num is None:
                continue

            headings.append(
                PDFHeading(
                    level=min(max(level, 1), 6),
                    title=title.strip(),
                    page_num=page_num,
                )
            )

        return headings

    except Exception as e:
        logger.warning(f"Failed to extract bookmarks: {e}")
        return []


def bookmarks_are_degenerate(headings: list[PDFHeading]) -> bool:
    """Return True when bookmark titles are generic exporter noise."""
    if len(headings) < _DEGENERATE_MIN_BOOKMARKS:
        return False
    generic = sum(1 for heading in headings if _GENERIC_TITLE_RE.match(heading.title.strip()))
    return generic / len(headings) >= _DEGENERATE_RATIO


def _build_page_number_map(pdf: PDF) -> dict[int, int]:
    """Build lookup from PDF page object IDs to 1-based page numbers.

    pdfminer outlines reference pages by object id. In pdfplumber these are
    exposed as `page.page_obj.pageid` (or legacy `objid`).
    """
    page_ref_map: dict[int, int] = {}

    for idx, page in enumerate(pdf.pages, 1):
        if hasattr(page, "page_obj"):
            for attr in ("pageid", "objid"):
                ref_id = getattr(page.page_obj, attr, None)
                if isinstance(ref_id, int):
                    page_ref_map[ref_id] = idx
                    break

    return page_ref_map


def _resolve_bookmark_page(
    page_ref: object,
    page_ref_map: dict[int, int],
    total_pages: int,
) -> int | None:
    """Resolve bookmark destination to 1-based page number.

    Handles multiple reference formats:
    - Integer object ID (via objid/pageid lookup)
    - Direct integer page index (0-based, converted to 1-based)
    - Lazy-resolved object references
    """
    ref_id = getattr(page_ref, "objid", None)
    if isinstance(ref_id, int):
        return page_ref_map.get(ref_id)

    if isinstance(page_ref, int):
        candidate = page_ref + 1
        if 1 <= candidate <= total_pages:
            return candidate
        return None

    if hasattr(page_ref, "resolve"):
        try:
            resolved = page_ref.resolve()
            for attr in ("pageid", "objid"):
                resolved_id = getattr(resolved, attr, None)
                if isinstance(resolved_id, int):
                    return page_ref_map.get(resolved_id)
        except Exception:
            pass

    return None
