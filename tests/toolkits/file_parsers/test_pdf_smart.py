"""Tests for SmartPDFParser (PDF parser with OCR fallback)."""

import tempfile
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.file_parsers import SmartPDFParser, get_parser
from myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor import (
    PDFExtractConfig,
    PDFExtractResult,
)


def _build_minimal_pdf_bytes(text: str) -> bytes:
    """Build a minimal valid PDF 1.4 with a single text page."""
    stream_content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    stream_bytes = stream_content.encode("latin-1")
    stream_len = len(stream_bytes)

    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n",
        f"4 0 obj\n<< /Length {stream_len} >>\nstream\n".encode("latin-1") + stream_bytes + b"\nendstream\nendobj\n",
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


@pytest.fixture
def real_text_pdf() -> str:
    """Write a real single-page PDF with text layer to a temp file."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, mode="wb") as tmp:
        tmp.write(_build_minimal_pdf_bytes("SmartParser contract terms"))
        tmp.flush()
        return tmp.name


@pytest.fixture
def smart_parser() -> SmartPDFParser:
    return SmartPDFParser()


class TestSmartPDFParser:
    """Parser behavior over the smart extraction orchestrator."""

    @pytest.mark.asyncio
    async def test_parse_returns_extracted_text(self, smart_parser):
        result = PDFExtractResult(
            text="parsed pdf text",
            page_count=1,
            parsed_pages=1,
            strategy="text",
        )
        with patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_smart.extract_pdf_content",
            new_callable=AsyncMock,
            return_value=result,
        ) as mock_extract:
            text = await smart_parser.parse("doc.pdf")

        assert text == "parsed pdf text"
        mock_extract.assert_awaited_once_with("doc.pdf", smart_parser._config)

    @pytest.mark.asyncio
    async def test_scanned_pdf_ocr_text_surfaces(self):
        """Scanned PDFs (sparse text) return OCR text through parse()."""
        result = PDFExtractResult(
            text="[Page 1]\ncontract terms",
            page_count=1,
            parsed_pages=1,
            strategy="image",
        )
        with patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_smart.extract_pdf_content",
            new_callable=AsyncMock,
            return_value=result,
        ):
            text = await SmartPDFParser().parse("scan.pdf")

        assert "contract terms" in text

    def test_default_config_targets_text_output(self):
        config = SmartPDFParser()._config
        assert isinstance(config, PDFExtractConfig)
        assert config.extract_embedded_images is False
        assert config.table_format == "inline"

    def test_custom_config_forwarded(self):
        config = PDFExtractConfig(extract_embedded_images=False, max_pages=10)
        parser = SmartPDFParser(config=config)
        assert parser._config is config

    def test_supported_extensions(self):
        assert SmartPDFParser().supported_extensions == [".pdf"]

    @pytest.mark.asyncio
    async def test_parse_real_text_pdf_returns_text(self, real_text_pdf):
        """Real PDF with text layer parses through the full chain (no mocks)."""
        text = await SmartPDFParser().parse(real_text_pdf)
        assert "SmartParser contract terms" in text

    @pytest.mark.asyncio
    async def test_get_parser_parses_real_pdf(self, real_text_pdf):
        """get_parser('.pdf') -> SmartPDFParser parses a real PDF end-to-end."""
        parser = get_parser(real_text_pdf)
        assert isinstance(parser, SmartPDFParser)
        text = await parser.parse(real_text_pdf)
        assert "SmartParser contract terms" in text


class TestGetParserRegistration:
    """get_parser('.pdf') returns the smart parser (OCR fallback wired in)."""

    def test_get_parser_pdf_returns_smart_parser(self):
        parser = get_parser("document.pdf")
        assert isinstance(parser, SmartPDFParser)
        assert parser.supported_extensions == [".pdf"]
