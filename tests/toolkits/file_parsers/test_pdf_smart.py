"""Tests for SmartPDFParser (PDF parser with OCR fallback)."""

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.file_parsers import SmartPDFParser, get_parser
from myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor import (
    PDFExtractConfig,
    PDFExtractResult,
)


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


class TestGetParserRegistration:
    """get_parser('.pdf') returns the smart parser (OCR fallback wired in)."""

    def test_get_parser_pdf_returns_smart_parser(self):
        parser = get_parser("document.pdf")
        assert isinstance(parser, SmartPDFParser)
        assert parser.supported_extensions == [".pdf"]
