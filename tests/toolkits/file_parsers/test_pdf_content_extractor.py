"""Tests for the smart PDF content extraction pipeline.

Uses pypdfium2 to generate minimal PDF fixtures in-memory,
then exercises text, hybrid, and image strategies with ablation filtering.
"""

import base64
import io
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor import (
    PDFExtractConfig,
    PDFExtractResult,
    PDFImageContent,
    _extract_text_sync,
    extract_pdf_content,
)

# ---------------------------------------------------------------------------
# Fixtures: generate real PDFs using pypdfium2
# ---------------------------------------------------------------------------


def _make_text_pdf(text_content: str = "Hello World " * 80) -> Path:
    """Generate a minimal 1-page PDF with text using raw PDF 1.4 bytes."""
    pdf_bytes = _build_minimal_pdf_bytes(text_content)

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.write(pdf_bytes)
    tmp.flush()
    tmp.close()
    return Path(tmp.name)


def _build_minimal_pdf_bytes(text: str) -> bytes:
    """Build a minimal valid PDF with a single text page from raw bytes."""
    # This creates a minimal valid PDF 1.4 document with a single page containing text
    stream_content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    stream_bytes = stream_content.encode("latin-1")
    stream_len = len(stream_bytes)

    objects = [
        # obj 1: catalog
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        # obj 2: pages
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        # obj 3: page
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n",
        # obj 4: content stream
        f"4 0 obj\n<< /Length {stream_len} >>\nstream\n".encode("latin-1") + stream_bytes + b"\nendstream\nendobj\n",
        # obj 5: font
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]

    body = b""
    offsets: list[int] = []
    header = b"%PDF-1.4\n"
    pos = len(header)

    for obj in objects:
        offsets.append(pos)
        body += obj
        pos += len(obj)

    xref_pos = pos
    xref = f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    for offset in offsets:
        xref += f"{offset:010d} 00000 n \n"

    trailer = f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"

    return header + body + xref.encode("latin-1") + trailer.encode("latin-1")


def _make_sparse_pdf() -> Path:
    """Generate a PDF with almost no text (triggers image fallback)."""
    return _make_text_pdf(text_content="x")


# ---------------------------------------------------------------------------
# Unit tests for _extract_text_sync
# ---------------------------------------------------------------------------


class TestExtractTextSync:
    """Tests for the synchronous text extraction helper."""

    def test_extracts_text_from_valid_pdf(self):
        pdf_path = _make_text_pdf()
        try:
            text, page_count, tables = _extract_text_sync(str(pdf_path), max_pages=20)
            assert len(text.strip()) > 0
            assert page_count >= 1
            assert isinstance(tables, list)
        finally:
            pdf_path.unlink(missing_ok=True)

    def test_raises_on_missing_file(self):
        with pytest.raises(FileNotFoundError):
            _extract_text_sync("/nonexistent/fake.pdf", max_pages=5)


# ---------------------------------------------------------------------------
# Integration tests for extract_pdf_content
# ---------------------------------------------------------------------------


class TestExtractPdfContent:
    """Integration tests for the async extraction pipeline."""

    @pytest.mark.asyncio
    async def test_text_rich_pdf_uses_hybrid_strategy(self):
        """A text-rich PDF should use 'hybrid' strategy by default."""
        pdf_path = _make_text_pdf()
        try:
            config = PDFExtractConfig(max_pages=5, extract_embedded_images=True)
            result = await extract_pdf_content(str(pdf_path), config)

            assert isinstance(result, PDFExtractResult)
            assert result.strategy == "hybrid"
            assert result.page_count >= 1
            assert len(result.text.strip()) > 0
        finally:
            pdf_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_text_only_when_embedded_disabled(self):
        """With extract_embedded_images=False, strategy should be 'text'."""
        pdf_path = _make_text_pdf()
        try:
            config = PDFExtractConfig(extract_embedded_images=False)
            result = await extract_pdf_content(str(pdf_path), config)

            assert result.strategy == "text"
            assert len(result.images) == 0
        finally:
            pdf_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_sparse_pdf_uses_image_strategy(self):
        """A PDF with almost no text should fall back to 'image' strategy."""
        pdf_path = _make_sparse_pdf()
        try:
            config = PDFExtractConfig(min_text_chars=200)
            result = await extract_pdf_content(str(pdf_path), config)

            # image when pypdfium2 renders; text when it's unavailable
            assert result.strategy in ("image", "text")
            assert result.page_count >= 1
        finally:
            pdf_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_file_not_found_raises(self):
        """Should raise FileNotFoundError for missing PDF."""
        with pytest.raises(FileNotFoundError):
            await extract_pdf_content("/nonexistent/path/fake.pdf")

    @pytest.mark.asyncio
    async def test_default_config_used_when_none(self):
        """When config=None, PDFExtractConfig defaults should be used."""
        pdf_path = _make_text_pdf()
        try:
            result = await extract_pdf_content(str(pdf_path), config=None)
            assert isinstance(result, PDFExtractResult)
            assert result.page_count >= 1
        finally:
            pdf_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_image_trace_populated_when_images_filtered(self):
        """When images are extracted and filtered, image_trace should be populated."""
        pdf_path = _make_text_pdf()
        try:
            # Create a valid multi-color image (passes filter)
            valid_img = Image.new("RGB", (200, 200), color="white")
            draw = ImageDraw.Draw(valid_img)
            draw.rectangle([0, 0, 100, 200], fill="red")
            draw.rectangle([100, 0, 200, 200], fill="blue")
            buf = io.BytesIO()
            valid_img.save(buf, format="PNG")
            valid_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

            # A tiny noise image (will be dropped by size filter)
            noise_img = Image.new("RGB", (10, 10), color="black")
            buf2 = io.BytesIO()
            noise_img.save(buf2, format="PNG")
            noise_b64 = base64.b64encode(buf2.getvalue()).decode("ascii")

            mock_images = [
                PDFImageContent(data=valid_b64),
                PDFImageContent(data=noise_b64),
            ]

            with patch(
                "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor._extract_embedded_images_sync",
                return_value=mock_images,
            ):
                config = PDFExtractConfig(extract_embedded_images=True)
                result = await extract_pdf_content(str(pdf_path), config)

            assert result.strategy == "hybrid"
            assert len(result.images) == 1
            assert result.image_trace["total_processed"] == 2
            assert result.image_trace["kept_count"] == 1
            assert result.image_trace["dropped_count"] == 1
            assert "size_too_small" in result.image_trace["drop_reasons"]
        finally:
            pdf_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_no_embedded_images_returns_empty_trace(self):
        """When no embedded images are found, trace should be empty dict."""
        pdf_path = _make_text_pdf()
        try:
            with patch(
                "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor._extract_embedded_images_sync",
                return_value=[],
            ):
                config = PDFExtractConfig(extract_embedded_images=True)
                result = await extract_pdf_content(str(pdf_path), config)

            assert len(result.images) == 0
            assert result.image_trace == {}
        finally:
            pdf_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Branch coverage: max_pages truncation, ImportError paths, render failures
# ---------------------------------------------------------------------------


class TestBranchCoverage:
    """Tests targeting specific uncovered branches for maximum coverage."""

    def test_max_pages_truncation(self):
        """When page_count > max_pages, text should be trimmed at the marker."""
        from myrm_agent_harness.toolkits.file_parsers.base import PDFParseResult
        from myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor import (
            _extract_text_sync,
        )

        # Simulate a 3-page PDF text output with page markers
        fake_text = "[Page 1]\nContent of page 1\n\n[Page 2]\nContent of page 2\n\n[Page 3]\nContent of page 3\n"
        fake_result = PDFParseResult(
            text=fake_text,
            tables=[],
            metadata={"page_count": 3},
        )

        # PDFPlumberParser is lazily imported inside _extract_text_sync,
        # so we patch at the source module where it's defined
        with patch("myrm_agent_harness.toolkits.file_parsers.pdf.PDFPlumberParser") as mock_parser:
            mock_parser.return_value.parse_sync.return_value = fake_result
            text, page_count, tables = _extract_text_sync("/fake.pdf", max_pages=2)

        assert page_count == 3
        assert "[Page 1]" in text
        assert "[Page 2]" in text
        assert "[Page 3]" not in text
        assert len(tables) == 0

    def test_embedded_images_pdfplumber_import_error(self):
        """When pdfplumber is unavailable, embedded extraction returns empty list."""
        from myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor import (
            _extract_embedded_images_sync,
        )

        with patch.dict("sys.modules", {"pdfplumber": None}):
            result = _extract_embedded_images_sync("/fake.pdf", max_pages=5)
        assert result == []

    @pytest.mark.asyncio
    async def test_sparse_pdf_pypdfium2_import_error_fallback(self):
        """When pypdfium2 is unavailable for sparse PDF, should fallback to 'text'."""
        pdf_path = _make_text_pdf(text_content="x")
        try:
            with patch(
                "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor._render_pages_sync",
                side_effect=ImportError("pypdfium2 not available"),
            ):
                config = PDFExtractConfig(min_text_chars=200)
                result = await extract_pdf_content(str(pdf_path), config)

            assert result.strategy == "text"
            assert len(result.images) == 0
        finally:
            pdf_path.unlink(missing_ok=True)

    def test_render_pages_pypdfium2_import_error(self):
        """_render_pages_sync should raise ImportError when pypdfium2 missing."""
        from myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor import (
            _render_pages_sync,
        )

        with patch.dict("sys.modules", {"pypdfium2": None}), pytest.raises(ImportError, match="pypdfium2"):
            _render_pages_sync("/fake.pdf", max_pages=5, max_pixels=4_000_000)

    def test_embedded_images_outer_exception_handling(self):
        """When pdfplumber.open() raises, embedded extraction returns empty list."""
        from myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor import (
            _extract_embedded_images_sync,
        )

        with patch("pdfplumber.open", side_effect=RuntimeError("corrupt PDF")):
            result = _extract_embedded_images_sync("/fake.pdf", max_pages=5)
        assert result == []

    def test_embedded_images_valid_bbox_extraction(self):
        """Core loop: valid bbox with >40px dimensions produces a PDFImageContent."""
        from unittest.mock import MagicMock

        from myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor import (
            _extract_embedded_images_sync,
        )

        pil_img = Image.new("RGB", (200, 200), color="red")
        mock_rendered = MagicMock()
        mock_rendered.original = pil_img

        mock_cropped = MagicMock()
        mock_cropped.to_image.return_value = mock_rendered

        mock_page = MagicMock()
        mock_page.images = [{"x0": 10, "top": 10, "x1": 200, "bottom": 200}]
        mock_page.crop.return_value = mock_cropped

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdf.__len__ = MagicMock(return_value=1)

        with patch("pdfplumber.open", return_value=mock_pdf):
            result = _extract_embedded_images_sync("/fake.pdf", max_pages=5)

        assert len(result) == 1
        decoded = base64.b64decode(result[0].data)
        img = Image.open(io.BytesIO(decoded))
        assert img.size == (200, 200)

    def test_embedded_images_skips_invalid_bbox(self):
        """Bboxes where x1<=x0 or bottom<=top are skipped."""
        from unittest.mock import MagicMock

        from myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor import (
            _extract_embedded_images_sync,
        )

        mock_page = MagicMock()
        mock_page.images = [
            {"x0": 100, "top": 10, "x1": 50, "bottom": 200},  # x1 < x0
            {"x0": 10, "top": 200, "x1": 100, "bottom": 50},  # bottom < top
        ]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdf.__len__ = MagicMock(return_value=1)

        with patch("pdfplumber.open", return_value=mock_pdf):
            result = _extract_embedded_images_sync("/fake.pdf", max_pages=5)

        assert len(result) == 0

    def test_embedded_images_skips_tiny_bbox(self):
        """Bboxes smaller than 40px in either dimension are pre-filtered."""
        from unittest.mock import MagicMock

        from myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor import (
            _extract_embedded_images_sync,
        )

        mock_page = MagicMock()
        mock_page.images = [
            {"x0": 0, "top": 0, "x1": 30, "bottom": 200},  # width < 40
            {"x0": 0, "top": 0, "x1": 200, "bottom": 30},  # height < 40
        ]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdf.__len__ = MagicMock(return_value=1)

        with patch("pdfplumber.open", return_value=mock_pdf):
            result = _extract_embedded_images_sync("/fake.pdf", max_pages=5)

        assert len(result) == 0

    def test_embedded_images_crop_exception_skips_gracefully(self):
        """When crop() raises, that single image is skipped without crashing."""
        from unittest.mock import MagicMock

        from myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor import (
            _extract_embedded_images_sync,
        )

        mock_page = MagicMock()
        mock_page.images = [{"x0": 10, "top": 10, "x1": 200, "bottom": 200}]
        mock_page.crop.side_effect = ValueError("Cannot crop outside page bounds")

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdf.__len__ = MagicMock(return_value=1)

        with patch("pdfplumber.open", return_value=mock_pdf):
            result = _extract_embedded_images_sync("/fake.pdf", max_pages=5)

        assert len(result) == 0

    def test_embedded_images_multi_page_respects_max_pages(self):
        """Only first max_pages pages are processed."""
        from unittest.mock import MagicMock

        from myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor import (
            _extract_embedded_images_sync,
        )

        pil_img = Image.new("RGB", (100, 100), color="blue")
        mock_rendered = MagicMock()
        mock_rendered.original = pil_img

        mock_cropped = MagicMock()
        mock_cropped.to_image.return_value = mock_rendered

        def make_page():
            p = MagicMock()
            p.images = [{"x0": 0, "top": 0, "x1": 100, "bottom": 100}]
            p.crop.return_value = mock_cropped
            return p

        pages = [make_page() for _ in range(5)]
        mock_pdf = MagicMock()
        mock_pdf.pages = pages
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdf.__len__ = MagicMock(return_value=5)

        with patch("pdfplumber.open", return_value=mock_pdf):
            result = _extract_embedded_images_sync("/fake.pdf", max_pages=2)

        assert len(result) == 2
