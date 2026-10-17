"""Scan detection must judge page content, never the page-number markers.

The PDF parser writes a ``[Page N]`` marker for every page, blank ones included.
The extractor decides text vs. scanned from the real content and exposes a PDF
without real content as empty text, so consumers' empty-text fallbacks apply.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pypdfium2 as pdfium
import pytest
from PIL import Image, ImageDraw

from myrm_agent_harness.toolkits.file_parsers.pdf.pdf import PDFPlumberParser, count_content_chars
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_content_extractor import (
    PDFExtractConfig,
    PDFImageContent,
    extract_pdf_content,
)

_EXTRACTOR = "myrm_agent_harness.toolkits.file_parsers.pdf.pdf_content_extractor"


def _blank_pdf(path: Path, pages: int) -> Path:
    """PDF whose pages carry neither text nor images."""
    pdf = pdfium.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(200, 200)
    pdf.save(str(path))
    pdf.close()
    return path


def _image_only_pdf(path: Path, pages: int) -> Path:
    """Scanner-like PDF: one full-page raster per page, no text layer."""
    rasters: list[Image.Image] = []
    for page in range(pages):
        raster = Image.new("RGB", (600, 800), "white")
        drawing = ImageDraw.Draw(raster)
        for row in range(25):
            clause = f"Clause {page + 1}.{row + 1}: the parties agree to the terms."
            drawing.text((40, 40 + row * 28), clause, fill="black")
        rasters.append(raster)
    rasters[0].save(str(path), save_all=True, append_images=rasters[1:], resolution=100.0)
    return path


def _stub_pdf(path: Path) -> Path:
    """Existing file for tests that replace the text layer through a patched parser."""
    path.write_bytes(b"%PDF-1.4\n")
    return path


def _paged_text(page_count: int, content: str) -> str:
    """Parser-shaped text: a marker per page, real content on page 1 only."""
    parts = [f"[Page 1]\n{content}"] + [f"[Page {n}]\n" for n in range(2, page_count + 1)]
    return "\n\n".join(parts)


@pytest.fixture
def no_ocr():
    """OCR is optional and environment dependent; scan-detection tests isolate it."""
    with patch(f"{_EXTRACTOR}._ocr_rendered_pages_async", new_callable=AsyncMock, return_value="") as stub:
        yield stub


class TestCountContentChars:
    def test_marker_only_text_has_no_content(self):
        assert count_content_chars("[Page 1]\n\n\n[Page 2]\n") == 0

    def test_markers_do_not_add_to_real_content(self):
        assert count_content_chars("[Page 1]\nHello") == count_content_chars("Hello") == 5

    def test_tolerates_trailing_spaces_and_crlf(self):
        assert count_content_chars("[Page 3]  \r\n[Page 4]\r\n") == 0

    def test_inline_page_reference_is_content(self):
        sentence = "see [Page 21] for details"
        assert count_content_chars(sentence) == len(sentence)

    def test_empty_text(self):
        assert count_content_chars("") == 0


class TestParserMarkerRoundTrip:
    def test_every_marker_the_parser_writes_is_recognized(self, tmp_path):
        """Fails when the parser's marker format drifts from the matcher."""
        path = _blank_pdf(tmp_path / "blank.pdf", pages=25)

        text = PDFPlumberParser().parse_sync(str(path)).text

        assert "[Page 1]" in text
        assert "[Page 25]" in text
        assert count_content_chars(text) == 0


class TestScanGate:
    @pytest.mark.parametrize("pages", [5, 25])
    async def test_blank_pdf_is_scanned_regardless_of_page_count(self, tmp_path, no_ocr, pages):
        path = _blank_pdf(tmp_path / "blank.pdf", pages)

        result = await extract_pdf_content(str(path), PDFExtractConfig())

        assert result.strategy == "image"
        assert result.text == ""

    async def test_marker_only_text_is_exposed_as_empty_even_without_threshold(self, tmp_path, no_ocr):
        path = _blank_pdf(tmp_path / "blank.pdf", pages=3)

        result = await extract_pdf_content(str(path), PDFExtractConfig(min_text_chars=0))

        assert result.text == ""

    async def test_threshold_counts_content_not_markers(self, tmp_path, no_ocr):
        """190 real chars over 30 pages stay below 200 even though markers add ~300."""
        path = _stub_pdf(tmp_path / "stub.pdf")
        sparse = _paged_text(30, "x" * 190)

        with (
            patch(f"{_EXTRACTOR}._extract_text_sync", return_value=(sparse, 30, 30, [])),
            patch(f"{_EXTRACTOR}._render_pages_sync", return_value=[PDFImageContent(data="aGVsbG8=")]),
        ):
            result = await extract_pdf_content(str(path), PDFExtractConfig(min_text_chars=200))

        assert result.strategy == "image"

    async def test_real_text_at_threshold_keeps_text_strategy_and_markers(self, tmp_path, no_ocr):
        path = _stub_pdf(tmp_path / "stub.pdf")
        rich = _paged_text(30, "x" * 200)

        with (
            patch(f"{_EXTRACTOR}._extract_text_sync", return_value=(rich, 30, 30, [])),
            patch(f"{_EXTRACTOR}._extract_embedded_images_sync", return_value=[]),
        ):
            result = await extract_pdf_content(str(path), PDFExtractConfig(min_text_chars=200))

        assert result.strategy == "text"
        assert result.text == rich

    async def test_ocr_text_survives_for_a_pdf_without_text_layer(self, tmp_path):
        path = _blank_pdf(tmp_path / "blank.pdf", pages=3)

        with patch(
            f"{_EXTRACTOR}._ocr_rendered_pages_async",
            new_callable=AsyncMock,
            return_value="[Page 1]\nHello scanned document",
        ):
            result = await extract_pdf_content(str(path), PDFExtractConfig())

        assert result.strategy == "image"
        assert "Hello scanned document" in result.text


class TestScanWindow:
    """Scanned PDFs deliver at most the OCR window, and say so through parsed_pages."""

    async def test_image_only_scan_renders_the_ocr_window_and_reports_it(self, tmp_path, no_ocr):
        path = _image_only_pdf(tmp_path / "scan.pdf", pages=6)
        config = PDFExtractConfig(min_text_chars=20, ocr_pages=3)

        result = await extract_pdf_content(str(path), config)

        assert result.strategy == "image"
        assert result.page_count == 6
        assert result.parsed_pages == 3
        assert 1 <= len(result.images) <= 3

    async def test_disabled_ocr_window_reports_every_page(self, tmp_path, no_ocr):
        path = _image_only_pdf(tmp_path / "scan.pdf", pages=6)
        config = PDFExtractConfig(min_text_chars=20, ocr_pages=0)

        result = await extract_pdf_content(str(path), config)

        assert result.strategy == "image"
        assert result.parsed_pages == 6

    async def test_text_strategy_keeps_text_parse_page_count(self, tmp_path):
        path = _stub_pdf(tmp_path / "stub.pdf")
        rich = _paged_text(30, "x" * 400)

        with (
            patch(f"{_EXTRACTOR}._extract_text_sync", return_value=(rich, 30, 30, [])),
            patch(f"{_EXTRACTOR}._extract_embedded_images_sync", return_value=[]),
        ):
            result = await extract_pdf_content(str(path), PDFExtractConfig(ocr_pages=3))

        assert result.strategy == "text"
        assert result.parsed_pages == 30
