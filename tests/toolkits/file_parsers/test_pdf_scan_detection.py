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

from myrm_agent_harness.toolkits.file_parsers.pdf.pdf import PDFPlumberParser, count_content_chars, pages_without_text
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


class TestPagesWithoutText:
    """Per-page coverage: which delivered pages the text layer could not read."""

    def test_reports_only_the_empty_pages(self):
        text = "[Page 1]\nreal body\n[Page 2]\n\n[Page 3]\nmore body\n"
        assert pages_without_text(text) == [2]

    def test_all_pages_empty_on_a_scan(self):
        assert pages_without_text("[Page 1]\n\n[Page 2]\n\n[Page 3]\n\n") == [1, 2, 3]

    def test_no_markers_means_no_verdict(self):
        """Without markers there is no page to accuse; callers fall back to whole-text logic."""
        assert pages_without_text("just prose with no page markers") == []

    def test_sparse_page_with_real_text_is_not_accused(self):
        """Emptiness is the signal, not density: a short but readable page is not a scan."""
        text = "[Page 1]\nx\n[Page 2]\nbody\n"
        assert pages_without_text(text) == []

    def test_last_section_runs_to_end_of_text(self):
        assert pages_without_text("[Page 1]\nbody\n[Page 2]\n") == [2]


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
            patch(f"{_EXTRACTOR}._extract_embedded_images_sync", return_value=([], False)),
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

    async def test_pages_whose_ocr_failed_are_reported_not_dropped(self, tmp_path):
        """OCR that covers only some delivered pages must name the pages it missed.

        A failed page leaves no ``[Page N]`` marker behind, so deriving the gap from the
        markers alone reports nothing and the page vanishes from both the text and the
        coverage note.
        """
        path = _image_only_pdf(tmp_path / "scan.pdf", pages=4)

        with patch(
            f"{_EXTRACTOR}._ocr_rendered_pages_async",
            new_callable=AsyncMock,
            return_value="[Page 1]\nfirst\n[Page 3]\nthird",
        ):
            result = await extract_pdf_content(str(path), PDFExtractConfig(min_text_chars=20))

        assert result.pages_without_text == [2, 4]

    async def test_embedded_figures_do_not_mask_a_scanned_page_on_the_text_path(self, tmp_path):
        """Figures live *inside* pages, so their page numbers are not the delivered page set.

        Treating a figure-bearing page as the whole delivered set made the gap look empty
        and hid a scanned page that the text layer could not read.
        """
        path = _blank_pdf(tmp_path / "mixed.pdf", pages=4)
        # Page 1 carries real text; pages 2-4 are scans with no text objects.
        rich_text = "[Page 1]\n" + ("readable body " * 20) + "\n[Page 2]\n\n[Page 3]\n\n[Page 4]\n"
        figures = [PDFImageContent(data="aGVsbG8=", page_number=1)]

        with (
            patch(f"{_EXTRACTOR}._extract_text_sync", return_value=(rich_text, 4, 4, [])),
            patch(f"{_EXTRACTOR}._extract_embedded_images_sync", return_value=(figures, False)),
        ):
            result = await extract_pdf_content(str(path), PDFExtractConfig(min_text_chars=20))

        assert result.strategy == "text"
        assert result.pages_without_text == [2, 3, 4]


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

    async def test_partial_scan_reports_shortfall_through_parsed_pages_not_truncated(self, tmp_path, no_ocr):
        """A window-cut scan discloses missing pages via ``parsed_pages``, not ``truncated``.

        ``truncated`` belongs to the embedded-figure ceiling: its consumer copy speaks of figures,
        and a scan's shortfall is already visible to callers as ``parsed_pages < page_count``.
        Setting both would double-report one page shortfall through two different channels.
        """
        path = _image_only_pdf(tmp_path / "scan.pdf", pages=6)
        config = PDFExtractConfig(min_text_chars=20, ocr_pages=3)

        result = await extract_pdf_content(str(path), config)

        assert result.strategy == "image"
        assert result.parsed_pages < result.page_count
        assert "truncated" not in result.image_trace

    async def test_text_strategy_keeps_text_parse_page_count(self, tmp_path):
        path = _stub_pdf(tmp_path / "stub.pdf")
        rich = _paged_text(30, "x" * 400)

        with (
            patch(f"{_EXTRACTOR}._extract_text_sync", return_value=(rich, 30, 30, [])),
            patch(f"{_EXTRACTOR}._extract_embedded_images_sync", return_value=([], False)),
        ):
            result = await extract_pdf_content(str(path), PDFExtractConfig(ocr_pages=3))

        assert result.strategy == "text"
        assert result.parsed_pages == 30


def _figure_bytes(page: int, width: int = 80, height: int = 60) -> bytes:
    """Deterministic, non-uniform RGB pixels so the ablation filter keeps each figure."""
    return bytes((page * 37 + index * 11) % 256 for index in range(width * height * 3))


def _text_with_figures_pdf(path: Path, pages: int) -> Path:
    """Text-rich pages that each embed one distinct figure (the OCR'd-scan / report shape)."""
    objects: list[bytes] = []
    kids = " ".join(f"{3 + 3 * i} 0 R" for i in range(pages))
    font_id = 3 + 3 * pages
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode())
    for page in range(pages):
        _page_id, content_id, image_id = 3 + 3 * page, 4 + 3 * page, 5 + 3 * page
        sentence = " ".join(f"paragraph{page + 1}token{token}" for token in range(80))
        content = f"BT /F1 10 Tf 40 740 Td ({sentence}) Tj ET\nq 100 0 0 100 40 300 cm /Im0 Do Q".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> /XObject << /Im0 {image_id} 0 R >> >> >>".encode()
        )
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
        figure = _figure_bytes(page)
        objects.append(
            f"<< /Type /XObject /Subtype /Image /Width 80 /Height 60 /ColorSpace /DeviceRGB "
            f"/BitsPerComponent 8 /Length {len(figure)} >>\nstream\n".encode()
            + figure
            + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    start_xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start_xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    return path


class TestEmbeddedImageCeiling:
    """The embedded-image path is a delivery channel too, so it obeys the same window."""

    async def test_figures_are_capped_at_the_ocr_window(self, tmp_path):
        path = _text_with_figures_pdf(tmp_path / "figures.pdf", pages=6)
        config = PDFExtractConfig(min_text_chars=20, max_pages=500, ocr_pages=3)

        result = await extract_pdf_content(str(path), config)

        assert len(result.images) <= 3
        assert result.image_trace["total_processed"] <= 3

    async def test_ceiling_reports_truncation_when_it_bites(self, tmp_path):
        path = _text_with_figures_pdf(tmp_path / "figures.pdf", pages=6)
        config = PDFExtractConfig(min_text_chars=20, max_pages=500, ocr_pages=3)

        result = await extract_pdf_content(str(path), config)

        assert result.image_trace["truncated"] is True

    async def test_short_document_is_not_reported_as_truncated(self, tmp_path):
        path = _text_with_figures_pdf(tmp_path / "figures.pdf", pages=2)
        config = PDFExtractConfig(min_text_chars=20, max_pages=500, ocr_pages=30)

        result = await extract_pdf_content(str(path), config)

        assert "truncated" not in result.image_trace

    async def test_zero_window_means_no_ceiling(self, tmp_path):
        """ocr_pages=0 disables OCR; vision-only consumers still get every page's figure."""
        path = _text_with_figures_pdf(tmp_path / "figures.pdf", pages=4)
        config = PDFExtractConfig(min_text_chars=20, max_pages=4, ocr_pages=0)

        result = await extract_pdf_content(str(path), config)

        assert len(result.images) == 4
        assert "truncated" not in result.image_trace
