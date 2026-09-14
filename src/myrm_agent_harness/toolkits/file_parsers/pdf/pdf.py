"""PDFPlumberParser: text/table parsing with structure resolution.

[INPUT]
- base::FileParser (POS: File parser base classes and data structures)
- base::PDFHeading (POS: File parser base classes and data structures)
- base::PDFParseResult (POS: File parser base classes and data structures)
- base::PDFTable (POS: File parser base classes and data structures)
- pdf_bookmarks::extract_bookmarks (POS: Bookmark source of the PDF heading pipeline, owning outline walking and page resolution)
- pdf_bookmarks::bookmarks_are_degenerate (POS: Bookmark source of the PDF heading pipeline, owning outline walking and page resolution)
- pdf_cross_page::stitch_cross_page_tables (POS: Cross-page table stitching for boundary table fragments with precision-first guards)
- pdf_heading_pipeline::build_numbering_cues (POS: Heading fusion and in-place placement for PDF page text)
- pdf_heading_pipeline::fuse_headings (POS: Heading fusion and in-place placement for PDF page text)
- pdf_heading_pipeline::insert_headings_into_page_text (POS: Heading fusion and in-place placement for PDF page text)
- pdf_numbering::detect_numbering_headings (POS: Clause-numbering heading detection for bookmark-less PDFs with precision-first guards)
- pdf_numbering::filter_repeated_titles (POS: Clause-numbering heading detection for bookmark-less PDFs with precision-first guards)
- pdf_tables::extract_page_tables (POS: Table extraction, stitching finalization and Markdown/L0 rendering for PDF pages)
- pdf_tables::finalize_tables (POS: Table extraction, stitching finalization and Markdown/L0 rendering for PDF pages)
- pdfplumber.PDF / pdfplumber.page.Page: document and page objects

[OUTPUT]
- PDFPlumberParser: PDF parser with layout text, Markdown tables, cross-page
  stitching and bookmark/numbering/font heading resolution

[POS]
pdfplumber-based PDF parser orchestrator: page parsing (sequential/parallel),
heading composition, cross-page stitching and text/table merging, with an
optional physical ``max_pages`` slice.
"""

from __future__ import annotations

import asyncio
import logging
import typing
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from myrm_agent_harness.toolkits.file_parsers.base import (
    FileParser,
    PDFHeading,
    PDFParseResult,
    PDFTable,
)
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_bookmarks import (
    bookmarks_are_degenerate,
    extract_bookmarks,
)
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_cross_page import (
    stitch_cross_page_tables,
)
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_heading_pipeline import (
    build_numbering_cues,
    fuse_headings,
    insert_headings_into_page_text,
)
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_numbering import (
    detect_numbering_headings,
    filter_repeated_titles,
)
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_tables import (
    extract_page_tables,
    finalize_tables,
)

if TYPE_CHECKING:
    import pdfplumber.page
    from pdfplumber.pdf import PDF

logger = logging.getLogger(__name__)


class PDFPlumberParser(FileParser):
    """PDF file parser using pdfplumber

    Performance:
    - Small/medium files (< 50 pages): Excellent
    - Large files (> 100 pages): Recommend enabling parallel processing

    Features:
    - Text extraction with layout preservation
    - Table extraction with Markdown formatting
    - Bookmark/outline extraction with nested hierarchy
    - Numbering/font heading fallback when bookmarks are absent or generic
    - Cross-page table stitching for tables split by page breaks
    """

    def __init__(
        self,
        extract_tables: bool = True,
        extract_bookmarks: bool = True,
        table_settings: dict[str, str | int] | None = None,
        table_format: Literal["inline", "placeholder"] = "inline",
        parallel: bool = False,
        max_workers: int = 4,
        heading_detection: Literal["bookmarks", "font", "auto"] = "auto",
        max_pages: int | None = None,
        stitch_tables: bool = True,
    ):
        self._extract_tables = extract_tables
        self._should_extract_bookmarks = extract_bookmarks
        self._table_format = table_format
        self._parallel = parallel
        self._max_workers = max_workers
        self._heading_detection = heading_detection
        self._max_pages = max_pages
        self._stitch_tables = stitch_tables
        self._table_settings = table_settings or {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
            "intersection_tolerance": 3,
            "snap_tolerance": 3,
            "join_tolerance": 3,
        }

    async def parse(self, file_path: str) -> str:
        """Parse PDF file and return text (including tables as Markdown)"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        result = await asyncio.to_thread(self.parse_sync, file_path)

        logger.info(
            "PDF parsing completed: %s, length: %d chars, tables: %d, pages: %s",
            path.name,
            len(result.text),
            len(result.tables),
            result.metadata.get("page_count", "unknown"),
        )

        return result.text

    async def parse_with_tables(self, file_path: str) -> PDFParseResult:
        """Parse PDF and return structured result (text + tables + metadata)"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        result = await asyncio.to_thread(self.parse_sync, file_path)
        logger.info("PDF parsing with tables completed: %s", path.name)
        return result

    def parse_sync(self, file_path: str) -> PDFParseResult:
        """Synchronously parse PDF (core logic)

        Public sync interface for use in thread pools or non-async contexts.
        For async usage, prefer `parse()` or `parse_with_tables()`.
        """
        try:
            import pdfplumber
        except ImportError as e:
            raise ImportError("pdfplumber is not installed. Run: uv add pdfplumber") from e

        all_tables: list[PDFTable] = []
        failed_pages: list[int] = []
        page_texts: dict[int, str] = {}
        page_errors: dict[int, str] = {}

        with pdfplumber.open(file_path) as pdf:
            page_count = len(pdf.pages)
            pages_to_process = pdf.pages[: self._max_pages] if self._max_pages is not None else pdf.pages
            process_count = len(pages_to_process)
            page_heights = _numeric_page_heights(pages_to_process)

            bookmark_headings = self._resolve_bookmark_headings(pdf)
            font_headings = self._resolve_font_headings(pdf, bookmark_headings)

            if self._parallel and process_count > 10:
                page_results = self._parse_parallel(pages_to_process)
            else:
                page_results = self._parse_sequential(pages_to_process)

            for page_num, (text, tables, error) in enumerate(page_results, start=1):
                if error:
                    failed_pages.append(page_num)
                    page_errors[page_num] = error
                    logger.warning("Page %d parsing failed: %s", page_num, error)
                page_texts[page_num] = text
                for table in tables:
                    table.page_number = page_num
                    all_tables.append(table)

            if self._stitch_tables and all_tables:
                all_tables = stitch_cross_page_tables(all_tables, page_heights)
            finalize_tables(all_tables)

            headings = self._resolve_headings(bookmark_headings, font_headings, page_texts, process_count)
            headings_by_page: dict[int, list[PDFHeading]] = defaultdict(list)
            for heading in headings:
                headings_by_page[heading.page_num].append(heading)

            text_parts: list[str] = []
            for page_num in range(1, process_count + 1):
                body = page_texts.get(page_num, "")
                if page_num in page_errors:
                    body = f"[Parsing Error: {page_errors[page_num]}]"
                inserted = insert_headings_into_page_text(body, headings_by_page.get(page_num, []))
                text_parts.append(f"[Page {page_num}]\n{inserted}")

            metadata: dict[str, str | int] = {
                "page_count": page_count,
                "parsed_pages": process_count,
                "table_count": len(all_tables),
                "failed_pages": len(failed_pages),
                "parser": "pdfplumber",
            }

            final_text = self._merge_text_and_tables(text_parts, all_tables)

            return PDFParseResult(text=final_text, tables=all_tables, metadata=metadata, headings=headings)

    def _resolve_bookmark_headings(self, pdf: PDF) -> list[PDFHeading]:
        """Bookmarks are authoritative; generic exporter titles fall back to detection."""
        if not self._should_extract_bookmarks or self._heading_detection not in ("bookmarks", "auto"):
            return []

        bookmarks = extract_bookmarks(pdf)
        if bookmarks and bookmarks_are_degenerate(bookmarks):
            logger.info("PDF bookmarks carry no structure (generic exporter titles); using detection")
            return []
        return bookmarks

    def _resolve_font_headings(self, pdf: PDF, bookmarks: list[PDFHeading]) -> list[PDFHeading]:
        """Font-size heading detection, used only when bookmarks carry no structure."""
        if bookmarks or self._heading_detection not in ("font", "auto"):
            return []

        from .pdf_font_heading import detect_headings_by_font

        headings: list[PDFHeading] = []
        for item in detect_headings_by_font(pdf):
            level = item.get("level")
            title = item.get("title")
            page_num = item.get("page_num")
            if isinstance(level, int) and isinstance(title, str) and isinstance(page_num, int):
                headings.append(PDFHeading(level=level, title=title, page_num=page_num))
        return headings

    def _resolve_headings(
        self,
        bookmark_headings: list[PDFHeading],
        font_headings: list[PDFHeading],
        page_texts: dict[int, str],
        process_count: int,
    ) -> list[PDFHeading]:
        """Compose the document structure from bookmarks or detection sources."""
        if bookmark_headings:
            return bookmark_headings
        if self._heading_detection not in ("font", "auto"):
            return []

        numbering = detect_numbering_headings(
            [page_texts.get(page_num, "") for page_num in range(1, process_count + 1)],
            cue_titles=build_numbering_cues(font_headings),
        )
        if numbering:
            numbering = filter_repeated_titles(numbering, process_count)
        return fuse_headings(numbering, font_headings)

    def _parse_sequential(
        self,
        pages: list[pdfplumber.page.Page],
    ) -> typing.Iterator[tuple[str, list[PDFTable], str | None]]:
        """Sequential parsing (page by page) with streaming output"""
        for page in pages:
            try:
                text = page.extract_text() or ""
                tables: list[PDFTable] = []
                if self._extract_tables:
                    tables = extract_page_tables(page, self._table_settings)
                yield (text, tables, None)
            except Exception as e:
                yield ("", [], f"{type(e).__name__}: {e}")
            finally:
                if hasattr(page, "close"):
                    page.close()  # Free cached page data immediately to prevent OOM on large PDFs

    def _parse_parallel(
        self,
        pages: list[pdfplumber.page.Page],
    ) -> typing.Iterator[tuple[str, list[PDFTable], str | None]]:
        """Parallel parsing (multi-threaded) with streaming ordered output"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            future_to_idx = {executor.submit(self._parse_single_page, page): idx for idx, page in enumerate(pages)}

            next_expected_idx = 0
            buffer: dict[int, tuple[str, list[PDFTable], str | None]] = {}

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = ("", [], f"{type(e).__name__}: {e}")

                if idx == next_expected_idx:
                    yield result
                    next_expected_idx += 1
                    # Yield any sequential results that have already completed and are waiting in buffer
                    while next_expected_idx in buffer:
                        yield buffer.pop(next_expected_idx)
                        next_expected_idx += 1
                else:
                    buffer[idx] = result

    def _parse_single_page(
        self,
        page: pdfplumber.page.Page,
    ) -> tuple[str, list[PDFTable], str | None]:
        """Parse single page (for parallel calls)"""
        try:
            text = page.extract_text() or ""
            tables: list[PDFTable] = []
            if self._extract_tables:
                tables = extract_page_tables(page, self._table_settings)
            return (text, tables, None)
        except Exception as e:
            return ("", [], f"{type(e).__name__}: {e}")
        finally:
            if hasattr(page, "close"):
                page.close()  # Free cached page data immediately to prevent OOM on large PDFs

    def _merge_text_and_tables(
        self,
        text_parts: list[str],
        tables: list[PDFTable],
    ) -> str:
        """Merge text and tables (generate final output with Markdown tables)"""
        tables_by_page: dict[int, list[PDFTable]] = {}
        for table in tables:
            tables_by_page.setdefault(table.page_number, []).append(table)

        merged: list[str] = []
        for i, text in enumerate(text_parts, start=1):
            merged.append(text)
            if i in tables_by_page:
                for table in tables_by_page[i]:
                    if self._table_format == "placeholder":
                        # Encapsulation mode: replace with unique ID for anti-fragmentation
                        merged.append(f"\n[TABLE_CAPSULE: {table.id}]\n{table.summary_l0}\n")
                    else:
                        # Inline mode: render the Markdown table in place
                        merged.append(f"\n{table.markdown}\n")

        return "\n\n".join(merged)

    @property
    def supported_extensions(self) -> list[str]:
        return [".pdf"]


def _numeric_page_heights(pages: list[pdfplumber.page.Page]) -> dict[int, float]:
    """1-based page heights; non-numeric test doubles are skipped."""
    heights: dict[int, float] = {}
    for page_num, page in enumerate(pages, start=1):
        value = getattr(page, "height", None)
        if isinstance(value, (int, float)) and value > 0:
            heights[page_num] = float(value)
    return heights
