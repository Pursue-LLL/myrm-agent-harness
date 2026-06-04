"""
[INPUT]
file_path: str (Path to PDF)
table_format: Literal["inline", "placeholder"]

[OUTPUT]
PDFPlumberParser: Core PDF text/table parser (supports parallel processing, bookmark injection, and table capsules)

[POS]

PDF parser based on pdfplumber. Implements text layout preservation, Markdown table
extraction, and PDF bookmark injection. Provides Placeholder Mode for advanced RAG,
outputting L0 table summaries to enhance vector retrieval.
"""

from __future__ import annotations

import asyncio
import logging
import typing
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from myrm_agent_harness.toolkits.file_parsers.base import FileParser, PDFParseResult, PDFTable

if TYPE_CHECKING:
    import pdfplumber
    import pdfplumber.page

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
    - Intelligent bookmark-to-page resolution
    - Font-based heading detection (fallback when no bookmarks)
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
    ):
        self._extract_tables = extract_tables
        self._should_extract_bookmarks = extract_bookmarks
        self._table_format = table_format
        self._parallel = parallel
        self._max_workers = max_workers
        self._heading_detection = heading_detection
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

        logger.warning(
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
        logger.warning("PDF parsing with tables completed: %s", path.name)
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

        all_text: list[str] = []
        all_tables: list[PDFTable] = []
        failed_pages: list[int] = []

        with pdfplumber.open(file_path) as pdf:
            page_count = len(pdf.pages)

            bookmarks: list[dict[str, Any]] = []
            bookmarks_by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)

            if self._should_extract_bookmarks and self._heading_detection in ("bookmarks", "auto"):
                bookmarks = self._extract_bookmarks(pdf)
                for bm in bookmarks:
                    if bm["page_num"] is not None:
                        bookmarks_by_page[bm["page_num"]].append(bm)

                resolved_count = sum(1 for bm in bookmarks if bm["page_num"] is not None)
                unresolved_count = len(bookmarks) - resolved_count

                logger.info(
                    f"PDF bookmarks: {len(bookmarks)} total, {resolved_count} resolved, {unresolved_count} unresolved"
                )

            if not bookmarks_by_page and self._heading_detection in ("font", "auto"):
                from myrm_agent_harness.toolkits.file_parsers.pdf_heading import detect_headings_by_font

                font_headings = detect_headings_by_font(pdf)
                for bm in font_headings:
                    if bm["page_num"] is not None:
                        bookmarks_by_page[bm["page_num"]].append(bm)

            if self._parallel and page_count > 10:
                page_results = self._parse_parallel(pdf)
            else:
                page_results = self._parse_sequential(pdf)

            for page_num, (text, tables, error) in enumerate(page_results, start=1):
                page_content_parts: list[str] = []

                page_bookmarks = bookmarks_by_page.get(page_num, [])
                for bm in page_bookmarks:
                    heading_prefix = "#" * bm["level"]
                    page_content_parts.append(f"{heading_prefix} {bm['title']}\n")

                if error:
                    failed_pages.append(page_num)
                    logger.warning("Page %d parsing failed: %s", page_num, error)
                    page_content_parts.append(f"[Parsing Error: {error}]")
                else:
                    if text.strip():
                        page_content_parts.append(text)

                    for idx, table in enumerate(tables):
                        table.page_number = page_num
                        table.table_index = idx
                        table.id = f"table_{page_num}_{idx}"
                        # Pre-render markdown and summary for L0/L2 representation
                        table.markdown = self._format_table_markdown(table)
                        table.summary_l0 = self._generate_table_summary_l0(table)
                        all_tables.append(table)

                if page_content_parts:
                    combined = "\n".join(page_content_parts)
                    all_text.append(f"[Page {page_num}]\n{combined}")

            metadata: dict[str, str | int] = {
                "page_count": page_count,
                "table_count": len(all_tables),
                "failed_pages": len(failed_pages),
                "parser": "pdfplumber",
            }

            if self._should_extract_bookmarks:
                metadata["bookmarks_total"] = len(bookmarks)
                metadata["bookmarks_resolved"] = sum(1 for bm in bookmarks if bm["page_num"] is not None)
                metadata["bookmarks_unresolved"] = sum(1 for bm in bookmarks if bm["page_num"] is None)

            final_text = self._merge_text_and_tables(all_text, all_tables)

            return PDFParseResult(text=final_text, tables=all_tables, metadata=metadata)

    def _parse_sequential(
        self,
        pdf: pdfplumber.PDF,
    ) -> typing.Iterator[tuple[str, list[PDFTable], str | None]]:
        """Sequential parsing (page by page) with streaming output"""
        for page in pdf.pages:
            try:
                text = page.extract_text() or ""
                tables: list[PDFTable] = []
                if self._extract_tables:
                    tables = self._extract_page_tables(page)
                yield (text, tables, None)
            except Exception as e:
                yield ("", [], f"{type(e).__name__}: {e}")
            finally:
                if hasattr(page, "close"):
                    page.close()  # Free cached page data immediately to prevent OOM on large PDFs

    def _parse_parallel(
        self,
        pdf: pdfplumber.PDF,
    ) -> typing.Iterator[tuple[str, list[PDFTable], str | None]]:
        """Parallel parsing (multi-threaded) with streaming ordered output"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            future_to_idx = {executor.submit(self._parse_single_page, page): idx for idx, page in enumerate(pdf.pages)}

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
                tables = self._extract_page_tables(page)
            return (text, tables, None)
        except Exception as e:
            return ("", [], f"{type(e).__name__}: {e}")
        finally:
            if hasattr(page, "close"):
                page.close()  # Free cached page data immediately to prevent OOM on large PDFs

    def _extract_page_tables(
        self,
        page: pdfplumber.page.Page,
    ) -> list[PDFTable]:
        """Extract tables from page"""
        tables: list[PDFTable] = []
        table_bboxes: list[tuple[float, float, float, float]] = []

        try:
            # Primary extraction: Explicit line-based table extraction
            raw_tables = page.find_tables(self._table_settings)

            for idx, raw_table in enumerate(raw_tables):
                table_data = raw_table.extract()
                if not table_data or not any(table_data):
                    continue

                cleaned = self._clean_table_data(table_data)
                if cleaned:
                    tables.append(
                        PDFTable(
                            page_number=0,
                            table_index=idx,
                            data=cleaned,
                            bbox=raw_table.bbox,
                        )
                    )
                    table_bboxes.append(raw_table.bbox)

            # Secondary extraction: Heuristic form/borderless table extraction (Lazy Trigger)
            page_text = page.extract_text() or ""
            
            # Lazy Trigger: Only trigger if there are multiple wide spaces indicating columnar alignment,
            # or if the page is extremely sparse (like a scanned invoice with few chars)
            import re
            trigger_heuristic = False
            # Check for multiple instances of 3+ spaces (including Tab and NBSP) which often indicate aligned columns
            if len(re.findall(r'[ \t\xa0]{3,}', page_text)) >= 3:
                trigger_heuristic = True
            elif len(page.chars) < 2000 and len(table_bboxes) == 0:
                # Sparse page without explicit tables, might be a borderless form
                trigger_heuristic = True

            if trigger_heuristic:
                # Memory-Dict Collision Masking: extract words once and filter in pure Python
                all_words = page.extract_words(keep_blank_chars=False, x_tolerance=3, y_tolerance=3)
                
                remaining_words = []
                for w in all_words:
                    w_x0, w_y0, w_x1, w_y1 = w["x0"], w["top"], w["x1"], w["bottom"]
                    in_any_bbox = False
                    for bx0, by0, bx1, by1 in table_bboxes:
                        # Check intersection
                        if not (w_x1 < bx0 or w_x0 > bx1 or w_y1 < by0 or w_y0 > by1):
                            in_any_bbox = True
                            break
                    if not in_any_bbox:
                        remaining_words.append(w)

                if remaining_words:
                    from myrm_agent_harness.toolkits.file_parsers.pdf_heuristic_table import extract_heuristic_tables_from_words
                    page_width = page.width if hasattr(page, "width") else 612.0
                    heuristic_tables = extract_heuristic_tables_from_words(remaining_words, float(page_width))

                    # Merge heuristic table results
                    base_idx = len(tables)
                    for h_idx, (h_data, h_bbox) in enumerate(heuristic_tables):
                        tables.append(
                            PDFTable(
                                page_number=0,
                                table_index=base_idx + h_idx,
                                data=h_data,
                                bbox=h_bbox,
                            )
                        )

            # Sort all tables by their vertical position (y0) to ensure correct reading order
            tables.sort(key=lambda t: t.bbox[1] if t.bbox else 0)

            # Reassign indices after sorting
            for idx, table in enumerate(tables):
                table.table_index = idx

        except Exception as e:
            logger.warning("Table extraction failed: %s", e)

        return tables

    @staticmethod
    def _clean_table_data(raw_table: list[list[str | None]]) -> list[list[str]]:
        """Clean table data: convert None to empty string, remove empty rows"""
        cleaned: list[list[str]] = []

        for row in raw_table:
            cleaned_row = [str(cell).strip() if cell else "" for cell in row]
            if any(cell for cell in cleaned_row):
                cleaned.append(cleaned_row)

        return cleaned

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
                        # Legacy inline mode
                        merged.append(f"\n{table.markdown}\n")

        return "\n\n".join(merged)

    @staticmethod
    def _format_table_markdown(table: PDFTable) -> str:
        """Format table as Markdown"""
        if not table.data or len(table.data) < 2:
            return f"**Table {table.table_index + 1}** (empty)"

        lines: list[str] = [
            f"**Table {table.table_index + 1}** (Page {table.page_number})",
            "",
        ]

        headers = [cell.replace("|", "\\|") for cell in table.data[0]]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        for row in table.data[1:]:
            cells = [cell.replace("|", "\\|") for cell in row]
            while len(cells) < len(headers):
                cells.append("")
            lines.append("| " + " | ".join(cells) + " |")

        return "\n".join(lines)

    @staticmethod
    def _generate_table_summary_l0(table: PDFTable) -> str:
        """Generates a heuristic L0 summary for the table capsule.

        Focuses on structural information for semantic indexing.
        """
        if not table.data:
            return "Empty table"

        header = table.data[0]
        row_count = len(table.data) - 1
        cols_summary = ", ".join([str(c) for c in header[:5]])
        if len(header) > 5:
            cols_summary += "..."

        summary = f"Structured Table on Page {table.page_number}. Rows: {row_count}. Headers: [{cols_summary}]. "

        # Add a glimpse of the first data row if available for better semantic matching
        if row_count > 0:
            first_row = table.data[1]
            row_preview = ", ".join([str(c) for c in first_row[:3]])
            summary += f"Data sample: {row_preview}."

        return summary.strip()

    def _extract_bookmarks(self, pdf: pdfplumber.PDF) -> list[dict[str, Any]]:
        """Extract bookmark structure from PDF outlines.

        Returns list of bookmarks with nested hierarchy resolved to flat list:
            [{"level": int (1-6), "title": str, "page_num": int (1-based) | None}]

        Note: page_num is None if bookmark destination cannot be resolved.
        """
        try:
            if not hasattr(pdf, "doc") or not hasattr(pdf.doc, "get_outlines"):
                logger.debug("PDF has no outline/bookmark support")
                return []

            outlines = list(pdf.doc.get_outlines())
            if not outlines:
                logger.debug("PDF has no bookmarks")
                return []

            page_ref_map = self._build_page_number_map(pdf)

            bookmarks: list[dict[str, Any]] = []
            for level, title, dest, _action, _se in outlines:
                if not title or not title.strip():
                    continue

                page_num = None
                try:
                    if dest and len(dest) > 0:
                        page_num = self._resolve_bookmark_page(dest[0], page_ref_map, len(pdf.pages))
                except Exception as e:
                    logger.debug(f"Failed to resolve bookmark '{title}': {e}")

                bookmarks.append(
                    {
                        "level": min(max(level, 1), 6),
                        "title": title.strip(),
                        "page_num": page_num,
                    }
                )

            return bookmarks

        except Exception as e:
            logger.warning(f"Failed to extract bookmarks: {e}")
            return []

    def _build_page_number_map(self, pdf: pdfplumber.PDF) -> dict[int, int]:
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
        self,
        page_ref: Any,
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

    @property
    def supported_extensions(self) -> list[str]:
        return [".pdf"]
