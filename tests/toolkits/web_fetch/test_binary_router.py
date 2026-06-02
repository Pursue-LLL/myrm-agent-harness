"""Tests for binary content detection and routing."""

from __future__ import annotations

import zipfile
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.web_fetch.binary_router import (
    _detect_extension_from_content_type,
    _detect_extension_from_disposition,
    _detect_extension_from_magic,
    _refine_zip_extension,
    detect_binary_extension,
    route_binary_content,
)


class TestDetectExtensionFromContentType:
    def test_pdf(self) -> None:
        assert _detect_extension_from_content_type("application/pdf") == ".pdf"

    def test_pdf_with_charset(self) -> None:
        assert _detect_extension_from_content_type("application/pdf; charset=utf-8") == ".pdf"

    def test_docx(self) -> None:
        ct = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        assert _detect_extension_from_content_type(ct) == ".docx"

    def test_xlsx(self) -> None:
        ct = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert _detect_extension_from_content_type(ct) == ".xlsx"

    def test_pptx(self) -> None:
        ct = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        assert _detect_extension_from_content_type(ct) == ".pptx"

    def test_image_png(self) -> None:
        assert _detect_extension_from_content_type("image/png") == ".png"

    def test_image_jpeg(self) -> None:
        assert _detect_extension_from_content_type("image/jpeg") == ".jpeg"

    def test_unknown(self) -> None:
        assert _detect_extension_from_content_type("application/octet-stream") is None

    def test_empty(self) -> None:
        assert _detect_extension_from_content_type("") is None

    def test_case_insensitive(self) -> None:
        assert _detect_extension_from_content_type("Application/PDF") == ".pdf"


class TestDetectExtensionFromDisposition:
    def test_basic_filename(self) -> None:
        headers = {"content-disposition": 'attachment; filename="report.pdf"'}
        assert _detect_extension_from_disposition(headers) == ".pdf"

    def test_filename_no_quotes(self) -> None:
        headers = {"content-disposition": "attachment; filename=report.xlsx"}
        assert _detect_extension_from_disposition(headers) == ".xlsx"

    def test_filename_star(self) -> None:
        headers = {"content-disposition": "attachment; filename*=UTF-8''report.docx"}
        assert _detect_extension_from_disposition(headers) == ".docx"

    def test_no_disposition(self) -> None:
        assert _detect_extension_from_disposition({}) is None

    def test_no_filename(self) -> None:
        headers = {"content-disposition": "inline"}
        assert _detect_extension_from_disposition(headers) is None

    def test_capitalized_header(self) -> None:
        headers = {"Content-Disposition": 'attachment; filename="file.pptx"'}
        assert _detect_extension_from_disposition(headers) == ".pptx"


class TestDetectExtensionFromMagic:
    def test_pdf_magic(self) -> None:
        data = b"%PDF-1.4 some content here..."
        assert _detect_extension_from_magic(data) == ".pdf"

    def test_png_magic(self) -> None:
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        assert _detect_extension_from_magic(data) == ".png"

    def test_jpeg_magic(self) -> None:
        data = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        assert _detect_extension_from_magic(data) == ".jpeg"

    def test_webp_magic(self) -> None:
        data = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 100
        assert _detect_extension_from_magic(data) == ".webp"

    def test_riff_non_webp(self) -> None:
        data = b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 100
        assert _detect_extension_from_magic(data) is None

    def test_ole2_magic(self) -> None:
        data = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100
        assert _detect_extension_from_magic(data) == ".doc"

    def test_too_short(self) -> None:
        assert _detect_extension_from_magic(b"\x89PNG") is None

    def test_unknown_format(self) -> None:
        data = b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09"
        assert _detect_extension_from_magic(data) is None

    def test_zip_docx(self) -> None:
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", "<doc/>")
            zf.writestr("[Content_Types].xml", "<types/>")
        data = buf.getvalue()
        assert _detect_extension_from_magic(data) == ".docx"

    def test_zip_xlsx(self) -> None:
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("xl/workbook.xml", "<wb/>")
            zf.writestr("[Content_Types].xml", "<types/>")
        data = buf.getvalue()
        assert _detect_extension_from_magic(data) == ".xlsx"

    def test_zip_pptx(self) -> None:
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("ppt/presentation.xml", "<pres/>")
            zf.writestr("[Content_Types].xml", "<types/>")
        data = buf.getvalue()
        assert _detect_extension_from_magic(data) == ".pptx"


class TestRefineZipExtension:
    def test_generic_zip(self) -> None:
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "hello")
        assert _refine_zip_extension(buf.getvalue()) == ".zip"

    def test_bad_zip(self) -> None:
        assert _refine_zip_extension(b"PK\x03\x04garbage") == ".zip"


class TestDetectBinaryExtension:
    def test_content_type_priority(self) -> None:
        headers = {
            "content-type": "application/pdf",
            "content-disposition": 'attachment; filename="doc.docx"',
        }
        assert detect_binary_extension(headers, b"%PDF-1.4") == ".pdf"

    def test_fallback_to_disposition(self) -> None:
        headers = {
            "content-type": "application/octet-stream",
            "content-disposition": 'attachment; filename="report.xlsx"',
        }
        assert detect_binary_extension(headers, b"") == ".xlsx"

    def test_fallback_to_magic(self) -> None:
        headers = {"content-type": "application/octet-stream"}
        data = b"%PDF-1.7 content..."
        assert detect_binary_extension(headers, data) == ".pdf"

    def test_all_layers_fail(self) -> None:
        headers = {"content-type": "application/octet-stream"}
        data = b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09"
        assert detect_binary_extension(headers, data) is None


class TestRouteBinaryContent:
    @pytest.mark.asyncio
    async def test_oversized_content_returns_none(self) -> None:
        huge = b"\x00" * (21 * 1024 * 1024)
        result = await route_binary_content(huge, {"content-type": "application/pdf"}, "http://example.com/big.pdf")
        assert result is None

    @pytest.mark.asyncio
    async def test_unrecognized_format_returns_none(self) -> None:
        data = b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09"
        headers = {"content-type": "application/octet-stream"}
        result = await route_binary_content(data, headers, "http://example.com/unknown")
        assert result is None

    @pytest.mark.asyncio
    async def test_successful_pdf_parse(self) -> None:
        mock_parser = AsyncMock()
        mock_parser.parse = AsyncMock(return_value="Parsed PDF content here")

        with patch(
            "myrm_agent_harness.toolkits.file_parsers.get_parser",
            return_value=mock_parser,
        ):
            data = b"%PDF-1.4 fake pdf content"
            headers = {"content-type": "application/pdf"}
            result = await route_binary_content(data, headers, "http://example.com/doc.pdf")

        assert result is not None
        assert result.page_content == "Parsed PDF content here"
        assert result.metadata["source_type"] == "binary_pdf"
        assert result.metadata["extension"] == ".pdf"
        assert result.metadata["url"] == "http://example.com/doc.pdf"

    @pytest.mark.asyncio
    async def test_empty_parse_result_returns_none(self) -> None:
        mock_parser = AsyncMock()
        mock_parser.parse = AsyncMock(return_value="")

        with patch(
            "myrm_agent_harness.toolkits.file_parsers.get_parser",
            return_value=mock_parser,
        ):
            data = b"%PDF-1.4 fake pdf"
            headers = {"content-type": "application/pdf"}
            result = await route_binary_content(data, headers, "http://example.com/empty.pdf")

        assert result is None

    @pytest.mark.asyncio
    async def test_parser_exception_returns_none(self) -> None:
        mock_parser = AsyncMock()
        mock_parser.parse = AsyncMock(side_effect=RuntimeError("Parse failed"))

        with patch(
            "myrm_agent_harness.toolkits.file_parsers.get_parser",
            return_value=mock_parser,
        ):
            data = b"%PDF-1.4 fake pdf"
            headers = {"content-type": "application/pdf"}
            result = await route_binary_content(data, headers, "http://example.com/bad.pdf")

        assert result is None

    @pytest.mark.asyncio
    async def test_unsupported_extension_zip_returns_none(self) -> None:
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "hello")
        data = buf.getvalue()
        headers = {"content-type": "application/octet-stream"}
        result = await route_binary_content(data, headers, "http://example.com/archive.zip")
        assert result is None

    @pytest.mark.asyncio
    async def test_content_truncation(self) -> None:
        long_text = "A" * 200_000
        mock_parser = AsyncMock()
        mock_parser.parse = AsyncMock(return_value=long_text)

        with patch(
            "myrm_agent_harness.toolkits.file_parsers.get_parser",
            return_value=mock_parser,
        ):
            data = b"%PDF-1.4 fake pdf"
            headers = {"content-type": "application/pdf"}
            result = await route_binary_content(data, headers, "http://example.com/long.pdf")

        assert result is not None
        assert len(result.page_content) == 100_000
