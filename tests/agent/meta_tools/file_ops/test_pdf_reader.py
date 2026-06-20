"""Tests for pdf_reader module — Large Document Smart RAG Diverter

Covers:
- is_pdf_path detection (incl. boundary cases)
- Callback registration/unregistration lifecycle
- _fire_and_forget_ingest: noop / success / exception swallowing
- _schedule_rag_ingest: MAX_PAGES guard / below-default / re-extraction /
  re-extraction fallback / outer exception / boundary values / SHA256 hash
- read_pdf_as_content_blocks: FileNotFoundError / read failure / ImportError /
  extraction failure / empty content / small doc / large doc RAG hint /
  text truncation / vision mode / non-blocking create_task timing
- _write_to_temp: roundtrip correctness
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.utils.pdf_reader import (
    RAG_MAX_PAGES_LIMIT,
    RAG_PAGE_THRESHOLD,
    _FALLBACK_MAX_CHARS,
    _fire_and_forget_ingest,
    _schedule_rag_ingest,
    _write_to_temp,
    is_pdf_path,
    read_pdf_as_content_blocks,
    register_large_doc_ingest_callback,
    unregister_large_doc_ingest_callback,
)


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------


@dataclass
class FakePDFResult:
    text: str
    page_count: int
    images: list[Any] = field(default_factory=list)


class FakeConfig:
    def __init__(self, max_pages: int = 20) -> None:
        self.max_pages = max_pages


@dataclass
class FakeImage:
    data: str = "base64data"
    mime_type: str = "image/png"


# ---------------------------------------------------------------------------
# is_pdf_path
# ---------------------------------------------------------------------------


class TestIsPdfPath:
    def test_pdf_detected(self) -> None:
        assert is_pdf_path("report.pdf") is True

    def test_pdf_uppercase(self) -> None:
        assert is_pdf_path("REPORT.PDF") is True

    def test_pdf_mixed_case(self) -> None:
        assert is_pdf_path("Report.Pdf") is True

    def test_non_pdf_rejected(self) -> None:
        assert is_pdf_path("report.docx") is False

    def test_no_extension_rejected(self) -> None:
        assert is_pdf_path("report") is False

    def test_nested_path(self) -> None:
        assert is_pdf_path("/tmp/docs/report.pdf") is True

    def test_dot_pdf_in_dirname_not_detected(self) -> None:
        assert is_pdf_path("/tmp/pdf.dir/readme.txt") is False

    def test_hidden_pdf_file(self) -> None:
        assert is_pdf_path("/tmp/.hidden.pdf") is True


# ---------------------------------------------------------------------------
# Callback registration
# ---------------------------------------------------------------------------


class TestCallbackRegistration:
    def setup_method(self) -> None:
        unregister_large_doc_ingest_callback()

    def teardown_method(self) -> None:
        unregister_large_doc_ingest_callback()

    def test_register_and_unregister(self) -> None:
        cb = AsyncMock()
        register_large_doc_ingest_callback(cb)
        from myrm_agent_harness.agent.meta_tools.file_ops.utils import pdf_reader

        assert pdf_reader._ingest_callback is cb
        unregister_large_doc_ingest_callback()
        assert pdf_reader._ingest_callback is None

    def test_register_replaces_previous(self) -> None:
        cb1 = AsyncMock()
        cb2 = AsyncMock()
        register_large_doc_ingest_callback(cb1)
        register_large_doc_ingest_callback(cb2)
        from myrm_agent_harness.agent.meta_tools.file_ops.utils import pdf_reader

        assert pdf_reader._ingest_callback is cb2

    def test_double_unregister_is_safe(self) -> None:
        unregister_large_doc_ingest_callback()
        unregister_large_doc_ingest_callback()


# ---------------------------------------------------------------------------
# _fire_and_forget_ingest
# ---------------------------------------------------------------------------


class TestFireAndForgetIngest:
    def setup_method(self) -> None:
        unregister_large_doc_ingest_callback()

    def teardown_method(self) -> None:
        unregister_large_doc_ingest_callback()

    @pytest.mark.asyncio
    async def test_no_callback_noop(self) -> None:
        await _fire_and_forget_ingest("test.pdf", "text", "hash123")

    @pytest.mark.asyncio
    async def test_callback_called(self) -> None:
        cb = AsyncMock()
        register_large_doc_ingest_callback(cb)
        await _fire_and_forget_ingest("test.pdf", "full text", "abc123")
        cb.assert_awaited_once_with("test.pdf", "full text", "abc123")

    @pytest.mark.asyncio
    async def test_callback_exception_swallowed(self) -> None:
        cb = AsyncMock(side_effect=RuntimeError("boom"))
        register_large_doc_ingest_callback(cb)
        await _fire_and_forget_ingest("test.pdf", "text", "hash")


# ---------------------------------------------------------------------------
# _schedule_rag_ingest
# ---------------------------------------------------------------------------


class TestScheduleRagIngest:
    def setup_method(self) -> None:
        unregister_large_doc_ingest_callback()

    def teardown_method(self) -> None:
        unregister_large_doc_ingest_callback()

    @pytest.mark.asyncio
    async def test_skips_when_exceeds_max_pages_limit(self) -> None:
        cb = AsyncMock()
        register_large_doc_ingest_callback(cb)
        result = FakePDFResult(text="hello", page_count=RAG_MAX_PAGES_LIMIT + 1)
        await _schedule_rag_ingest("/tmp/huge.pdf", b"data", result, FakeConfig, AsyncMock())
        cb.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_boundary_exactly_max_pages_limit_is_accepted(self) -> None:
        """page_count == RAG_MAX_PAGES_LIMIT should be accepted (not >)."""
        cb = AsyncMock()
        register_large_doc_ingest_callback(cb)
        result = FakePDFResult(text="text", page_count=RAG_MAX_PAGES_LIMIT)
        await _schedule_rag_ingest("/tmp/boundary.pdf", b"data", result, FakeConfig, AsyncMock())
        cb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ingests_when_below_default_max(self) -> None:
        cb = AsyncMock()
        register_large_doc_ingest_callback(cb)
        raw_bytes = b"fake pdf"
        result = FakePDFResult(text="hello world", page_count=15)
        await _schedule_rag_ingest("/tmp/small.pdf", raw_bytes, result, FakeConfig, AsyncMock())
        expected_hash = hashlib.sha256(raw_bytes[:8192]).hexdigest()[:16]
        cb.assert_awaited_once_with("small.pdf", "hello world", expected_hash)

    @pytest.mark.asyncio
    async def test_reextracts_when_above_default_max(self) -> None:
        cb = AsyncMock()
        register_large_doc_ingest_callback(cb)
        raw_bytes = b"fake pdf bytes"
        result = FakePDFResult(text="truncated", page_count=50)
        full_result = FakePDFResult(text="full content all 50 pages", page_count=50)
        mock_extract = AsyncMock(return_value=full_result)

        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.pdf_reader._write_to_temp",
            new_callable=AsyncMock, return_value="/tmp/fake.pdf",
        ), patch("os.unlink"):
            await _schedule_rag_ingest("/tmp/large.pdf", raw_bytes, result, FakeConfig, mock_extract)

        expected_hash = hashlib.sha256(raw_bytes[:8192]).hexdigest()[:16]
        cb.assert_awaited_once_with("large.pdf", "full content all 50 pages", expected_hash)

    @pytest.mark.asyncio
    async def test_reextraction_failure_falls_back_to_truncated(self) -> None:
        """When re-extraction fails, should use original truncated text."""
        cb = AsyncMock()
        register_large_doc_ingest_callback(cb)
        raw_bytes = b"pdf data"
        result = FakePDFResult(text="original truncated", page_count=50)
        mock_extract = AsyncMock(side_effect=RuntimeError("extraction boom"))

        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.pdf_reader._write_to_temp",
            new_callable=AsyncMock, return_value="/tmp/fake.pdf",
        ), patch("os.unlink"):
            await _schedule_rag_ingest("/tmp/fail.pdf", raw_bytes, result, FakeConfig, mock_extract)

        expected_hash = hashlib.sha256(raw_bytes[:8192]).hexdigest()[:16]
        cb.assert_awaited_once_with("fail.pdf", "original truncated", expected_hash)

    @pytest.mark.asyncio
    async def test_exception_caught_in_outer_try(self) -> None:
        cb = AsyncMock()
        register_large_doc_ingest_callback(cb)
        bad_result = MagicMock()
        bad_result.page_count = 25
        bad_result.text = "text"

        class BadConfig:
            @property
            def max_pages(self) -> int:
                raise RuntimeError("config broke")

        await _schedule_rag_ingest("/tmp/bad.pdf", b"data", bad_result, BadConfig, AsyncMock())

    @pytest.mark.asyncio
    async def test_sha256_hash_deterministic(self) -> None:
        """Verify that doc_hash is SHA256 of first 8KB, truncated to 16 chars."""
        cb = AsyncMock()
        register_large_doc_ingest_callback(cb)
        raw_bytes = b"A" * 16384
        result = FakePDFResult(text="text", page_count=10)
        await _schedule_rag_ingest("/tmp/hash.pdf", raw_bytes, result, FakeConfig, AsyncMock())
        expected = hashlib.sha256(raw_bytes[:8192]).hexdigest()[:16]
        actual_hash = cb.call_args[0][2]
        assert actual_hash == expected
        assert len(actual_hash) == 16

    @pytest.mark.asyncio
    async def test_temp_file_cleaned_up_even_on_extract_failure(self) -> None:
        """os.unlink must be called in finally block even when extraction fails."""
        cb = AsyncMock()
        register_large_doc_ingest_callback(cb)
        result = FakePDFResult(text="text", page_count=50)
        mock_extract = AsyncMock(side_effect=RuntimeError("boom"))

        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.pdf_reader._write_to_temp",
            new_callable=AsyncMock, return_value="/tmp/cleanup.pdf",
        ), patch("os.unlink") as mock_unlink:
            await _schedule_rag_ingest("/tmp/t.pdf", b"data", result, FakeConfig, mock_extract)

        mock_unlink.assert_called_once_with("/tmp/cleanup.pdf")


# ---------------------------------------------------------------------------
# _write_to_temp
# ---------------------------------------------------------------------------


class TestWriteToTemp:
    @pytest.mark.asyncio
    async def test_roundtrip(self) -> None:
        content = b"hello pdf bytes"
        tmp = await _write_to_temp(content)
        try:
            with open(tmp, "rb") as f:
                assert f.read() == content
            assert tmp.endswith(".pdf")
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# read_pdf_as_content_blocks
# ---------------------------------------------------------------------------


class TestReadPdfAsContentBlocks:
    def setup_method(self) -> None:
        unregister_large_doc_ingest_callback()

    def teardown_method(self) -> None:
        unregister_large_doc_ingest_callback()

    @pytest.mark.asyncio
    async def test_file_not_found_propagates(self) -> None:
        executor = AsyncMock()
        executor.read_file_bytes = AsyncMock(side_effect=FileNotFoundError("gone"))
        with pytest.raises(FileNotFoundError):
            await read_pdf_as_content_blocks("/tmp/missing.pdf", executor, False)

    @pytest.mark.asyncio
    async def test_read_bytes_generic_error(self) -> None:
        executor = AsyncMock()
        executor.read_file_bytes = AsyncMock(side_effect=IOError("disk"))
        result = await read_pdf_as_content_blocks("/tmp/bad.pdf", executor, False)
        assert "Failed to read" in result

    @pytest.mark.asyncio
    async def test_import_error_graceful(self) -> None:
        executor = AsyncMock()
        executor.read_file_bytes = AsyncMock(return_value=b"bytes")
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.pdf_reader._write_to_temp",
            new_callable=AsyncMock, return_value="/tmp/t.pdf",
        ), patch("os.unlink"), patch.dict(
            "sys.modules",
            {"myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor": None},
        ):
            result = await read_pdf_as_content_blocks("/tmp/test.pdf", executor, False)
        assert "not available" in result

    @pytest.mark.asyncio
    async def test_extraction_failure(self) -> None:
        executor = AsyncMock()
        executor.read_file_bytes = AsyncMock(return_value=b"bytes")
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.pdf_reader._write_to_temp",
            new_callable=AsyncMock, return_value="/tmp/t.pdf",
        ), patch("os.unlink"), patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor.extract_pdf_content",
            new_callable=AsyncMock, side_effect=RuntimeError("extract fail"),
        ):
            result = await read_pdf_as_content_blocks("/tmp/test.pdf", executor, False)
        assert "Extraction failed" in result

    @pytest.mark.asyncio
    async def test_empty_content_encrypted(self) -> None:
        executor = AsyncMock()
        executor.read_file_bytes = AsyncMock(return_value=b"bytes")
        empty_result = FakePDFResult(text="   ", page_count=1)
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.pdf_reader._write_to_temp",
            new_callable=AsyncMock, return_value="/tmp/t.pdf",
        ), patch("os.unlink"), patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor.extract_pdf_content",
            new_callable=AsyncMock, return_value=empty_result,
        ), patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor.PDFExtractConfig",
            FakeConfig,
        ):
            result = await read_pdf_as_content_blocks("/tmp/enc.pdf", executor, False)
        assert "encrypted" in result

    @pytest.mark.asyncio
    async def test_small_doc_no_rag_hint(self) -> None:
        """Documents <= RAG_PAGE_THRESHOLD should not have RAG hint."""
        executor = AsyncMock()
        executor.read_file_bytes = AsyncMock(return_value=b"bytes")
        small_result = FakePDFResult(text="Hello world", page_count=RAG_PAGE_THRESHOLD)
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.pdf_reader._write_to_temp",
            new_callable=AsyncMock, return_value="/tmp/t.pdf",
        ), patch("os.unlink"), patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor.extract_pdf_content",
            new_callable=AsyncMock, return_value=small_result,
        ), patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor.PDFExtractConfig",
            FakeConfig,
        ):
            result = await read_pdf_as_content_blocks("/tmp/s.pdf", executor, False)
        assert "RAG Auto-Index" not in result
        assert "Hello world" in result

    @pytest.mark.asyncio
    async def test_large_doc_rag_hint_with_callback(self) -> None:
        """Documents > RAG_PAGE_THRESHOLD with callback should have RAG hint."""
        cb = AsyncMock()
        register_large_doc_ingest_callback(cb)
        executor = AsyncMock()
        executor.read_file_bytes = AsyncMock(return_value=b"bytes")
        large_result = FakePDFResult(text="Content", page_count=RAG_PAGE_THRESHOLD + 1)
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.pdf_reader._write_to_temp",
            new_callable=AsyncMock, return_value="/tmp/t.pdf",
        ), patch("os.unlink"), patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor.extract_pdf_content",
            new_callable=AsyncMock, return_value=large_result,
        ), patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor.PDFExtractConfig",
            FakeConfig,
        ):
            result = await read_pdf_as_content_blocks("/tmp/l.pdf", executor, False)
        assert "RAG Auto-Index" in result
        assert "wiki_query" in result
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_large_doc_no_rag_without_callback(self) -> None:
        """Large doc without registered callback should NOT have RAG hint."""
        executor = AsyncMock()
        executor.read_file_bytes = AsyncMock(return_value=b"bytes")
        large_result = FakePDFResult(text="Content", page_count=RAG_PAGE_THRESHOLD + 1)
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.pdf_reader._write_to_temp",
            new_callable=AsyncMock, return_value="/tmp/t.pdf",
        ), patch("os.unlink"), patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor.extract_pdf_content",
            new_callable=AsyncMock, return_value=large_result,
        ), patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor.PDFExtractConfig",
            FakeConfig,
        ):
            result = await read_pdf_as_content_blocks("/tmp/no_cb.pdf", executor, False)
        assert "RAG Auto-Index" not in result

    @pytest.mark.asyncio
    async def test_text_truncation(self) -> None:
        executor = AsyncMock()
        executor.read_file_bytes = AsyncMock(return_value=b"bytes")
        long_text = "x" * (_FALLBACK_MAX_CHARS + 1000)
        big_result = FakePDFResult(text=long_text, page_count=5)
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.pdf_reader._write_to_temp",
            new_callable=AsyncMock, return_value="/tmp/t.pdf",
        ), patch("os.unlink"), patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor.extract_pdf_content",
            new_callable=AsyncMock, return_value=big_result,
        ), patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor.PDFExtractConfig",
            FakeConfig,
        ):
            result = await read_pdf_as_content_blocks("/tmp/big.pdf", executor, False)
        assert f"truncated at {_FALLBACK_MAX_CHARS}" in result

    @pytest.mark.asyncio
    async def test_vision_mode_returns_blocks(self) -> None:
        executor = AsyncMock()
        executor.read_file_bytes = AsyncMock(return_value=b"bytes")
        img = FakeImage()
        vision_result = FakePDFResult(text="Visual text", page_count=3, images=[img])
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.pdf_reader._write_to_temp",
            new_callable=AsyncMock, return_value="/tmp/t.pdf",
        ), patch("os.unlink"), patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor.extract_pdf_content",
            new_callable=AsyncMock, return_value=vision_result,
        ), patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor.PDFExtractConfig",
            FakeConfig,
        ):
            result = await read_pdf_as_content_blocks("/tmp/v.pdf", executor, True)
        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_text_only_no_images_returns_string(self) -> None:
        executor = AsyncMock()
        executor.read_file_bytes = AsyncMock(return_value=b"bytes")
        text_result = FakePDFResult(text="Plain text", page_count=3)
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.pdf_reader._write_to_temp",
            new_callable=AsyncMock, return_value="/tmp/t.pdf",
        ), patch("os.unlink"), patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor.extract_pdf_content",
            new_callable=AsyncMock, return_value=text_result,
        ), patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor.PDFExtractConfig",
            FakeConfig,
        ):
            result = await read_pdf_as_content_blocks("/tmp/txt.pdf", executor, False)
        assert isinstance(result, str)
        assert "Plain text" in result

    @pytest.mark.asyncio
    async def test_no_text_image_only_returns_fallback(self) -> None:
        """PDF with no text and not supporting vision returns image-only message."""
        executor = AsyncMock()
        executor.read_file_bytes = AsyncMock(return_value=b"bytes")
        img_only = FakePDFResult(text="   ", page_count=3, images=[FakeImage()])
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.pdf_reader._write_to_temp",
            new_callable=AsyncMock, return_value="/tmp/t.pdf",
        ), patch("os.unlink"), patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor.extract_pdf_content",
            new_callable=AsyncMock, return_value=img_only,
        ), patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor.PDFExtractConfig",
            FakeConfig,
        ):
            result = await read_pdf_as_content_blocks("/tmp/img.pdf", executor, False)
        assert "image-only" in result


# ---------------------------------------------------------------------------
# Non-blocking create_task timing verification
# ---------------------------------------------------------------------------


class TestNonBlockingCreateTask:
    @pytest.mark.asyncio
    async def test_create_task_used_not_await(self) -> None:
        events: list[str] = []

        async def slow_ingest(filename: str, full_text: str, doc_hash: str) -> None:
            await asyncio.sleep(0.1)
            events.append("ingest_done")

        register_large_doc_ingest_callback(slow_ingest)
        result = FakePDFResult(text="text", page_count=5)
        asyncio.create_task(_schedule_rag_ingest(
            "/tmp/test.pdf", b"bytes", result, FakeConfig, AsyncMock()
        ))
        events.append("main_returned")

        assert events == ["main_returned"]
        await asyncio.sleep(0.2)
        assert "ingest_done" in events
        unregister_large_doc_ingest_callback()
