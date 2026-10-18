import base64
import contextlib
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.meta_tools.file_ops.core.file_read_handlers import (
    build_multimodal_result as _build_multimodal_result,
)

_DUMMY_CONFIG = RunnableConfig()
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.mark.asyncio
async def test_build_multimodal_result_native_vision_success():
    """Vision-supported models receive native ImageContentBlock directly."""
    mock_executor = AsyncMock()
    mock_executor.read_file_bytes.return_value = _TINY_PNG

    blocks = await _build_multimodal_result(
        image_paths=["test.png"],
        pdf_paths=[],
        document_paths=[],
        text_paths=[],
        vault_paths=[],
        executor=mock_executor,
        skills=None,
        reason=None,
        url_errors=[],
        supports_vision=True,
        config=_DUMMY_CONFIG,
    )

    assert len(blocks) >= 1
    # Either returns text info block + image block or image block
    block_types = [getattr(b, "type", b.get("type") if isinstance(b, dict) else None) for b in blocks]
    assert "image_url" in block_types or any("image" in str(b) for b in blocks)
    mock_executor.read_file_bytes.assert_called_once_with("test.png")


@pytest.mark.asyncio
async def test_build_multimodal_result_vision_fallback_success():
    """Text-only models fall back gracefully to structured text descriptions."""
    mock_executor = AsyncMock()
    mock_executor.read_file_bytes.return_value = b"dummy"

    vision_fallback_model_cfg = {"model": "gpt-4o-mini", "api_key": "test"}

    with patch(
        "myrm_agent_harness.toolkits.llms.vision.fallback_engine.VisionFallbackEngine.describe_local_image",
        new_callable=AsyncMock,
    ) as mock_describe:
        mock_describe.return_value = "A mock fallback text description"

        blocks = await _build_multimodal_result(
            image_paths=["test.png"],
            pdf_paths=[],
            document_paths=[],
            text_paths=[],
            vault_paths=[],
            executor=mock_executor,
            skills=None,
            reason=None,
            url_errors=[],
            supports_vision=False,
            vision_fallback_model_cfg=vision_fallback_model_cfg,
            config=_DUMMY_CONFIG,
        )

        assert len(blocks) == 1
        assert "A mock fallback text description" in blocks[0]["text"]
        mock_describe.assert_called_once_with("test.png", mock_executor)


@pytest.mark.asyncio
async def test_build_multimodal_result_vision_fallback_failure():
    """Fallback failure degrades gracefully without crashing."""
    mock_executor = AsyncMock()

    vision_fallback_model_cfg = {"model": "gpt-4o-mini", "api_key": "test"}

    with patch(
        "myrm_agent_harness.toolkits.llms.vision.fallback_engine.VisionFallbackEngine.describe_local_image",
        new_callable=AsyncMock,
    ) as mock_describe:
        mock_describe.side_effect = Exception("Fallback API Error")

        blocks = await _build_multimodal_result(
            image_paths=["test.png"],
            pdf_paths=[],
            document_paths=[],
            text_paths=[],
            vault_paths=[],
            executor=mock_executor,
            skills=None,
            reason=None,
            url_errors=[],
            supports_vision=False,
            vision_fallback_model_cfg=vision_fallback_model_cfg,
            config=_DUMMY_CONFIG,
        )

        assert len(blocks) == 1
        assert "Vision analysis unavailable" in blocks[0]["text"]


@pytest.mark.asyncio
async def test_build_multimodal_result_no_vision_no_fallback():
    """Text-only model without fallback configured returns path & metadata."""
    mock_executor = AsyncMock()
    mock_executor.read_file_bytes.return_value = _TINY_PNG

    blocks = await _build_multimodal_result(
        image_paths=["test.png"],
        pdf_paths=[],
        document_paths=[],
        text_paths=[],
        vault_paths=[],
        executor=mock_executor,
        skills=None,
        reason=None,
        url_errors=[],
        supports_vision=False,
        vision_fallback_model_cfg=None,
        vision_fallback_model_cfgs=None,
        config=_DUMMY_CONFIG,
    )

    assert len(blocks) == 1
    assert "Current model does not support vision" in blocks[0]["text"]


def _pdf_extract_result(*, text: str, page_numbers: list[int]):
    """Build a PDFExtractResult whose page images carry real page provenance."""
    from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_content_extractor import (
        PDFExtractResult,
        PDFImageContent,
    )

    b64 = base64.b64encode(_TINY_PNG).decode("ascii")
    return PDFExtractResult(
        text=text,
        images=[PDFImageContent(data=b64, page_number=p) for p in page_numbers],
        page_count=len(page_numbers) or 1,
        parsed_pages=len(page_numbers) or 1,
        strategy="hybrid" if text else "image",
    )


def _patch_extract(result):
    return patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.utils.pdf_reader._write_to_temp",
        new=AsyncMock(return_value="/tmp/probe.pdf"),
    )


def _patch_pdf_pipeline(result, engine):
    """Patch the temp-file round-trip, the extractor, and the vision chain factory."""
    return (
        _patch_extract(result),
        patch("os.unlink"),
        patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf.pdf_content_extractor.extract_pdf_content",
            new=AsyncMock(return_value=result),
        ),
        patch(
            "myrm_agent_harness.toolkits.llms.vision.fallback_engine.create_vision_fallback_engine",
            return_value=engine,
        ),
    )


@pytest.mark.asyncio
async def test_pdf_scanned_pages_reach_text_only_model_through_vision_fallback():
    """A scanned PDF must not lose its pages just because the primary model is text-only.

    Regression: ``read_pdf_as_content_blocks`` gated page images behind
    ``supports_vision``, so the auxiliary chain never saw them and every scan page
    vanished with no textual trace.
    """
    from myrm_agent_harness.agent.meta_tools.file_ops.utils import pdf_reader as _pdf_reader

    result = _pdf_extract_result(text="", page_numbers=[1, 2])
    described: list[str] = []

    class _Engine:
        async def describe_image_b64(self, b64_data, mime_type, retry_count=1, prompt=None):
            described.append(mime_type)
            return f"page body {len(described)}"

    with contextlib.ExitStack() as stack:
        for ctx in _patch_pdf_pipeline(result, _Engine()):
            stack.enter_context(ctx)
        out = await _pdf_reader.read_pdf_as_content_blocks(
            "/tmp/probe.pdf",
            AsyncMock(),
            supports_vision=False,
            vision_fallback_model_cfg={"model": "gpt-4o-mini", "api_key": "test"},
        )

    text = "".join(dict(b).get("text", "") for b in out) if isinstance(out, list) else str(out)
    assert described == ["image/png", "image/png"]
    assert "page body 1" in text and "page body 2" in text
    assert "[Page 1]" in text and "[Page 2]" in text


@pytest.mark.asyncio
async def test_pdf_vision_fallback_reports_real_page_numbers_not_positions():
    """Labels must name the source page, never the position within the delivered batch.

    A mixed document renders only pages 4-8; labelling them 1-5 would send the model
    looking at the wrong pages.
    """
    from myrm_agent_harness.agent.meta_tools.file_ops.utils import pdf_reader as _pdf_reader

    result = _pdf_extract_result(text="page one body", page_numbers=[4, 5, 6, 7, 8])

    class _Engine:
        async def describe_image_b64(self, b64_data, mime_type, retry_count=1, prompt=None):
            return "scanned body"

    with contextlib.ExitStack() as stack:
        for ctx in _patch_pdf_pipeline(result, _Engine()):
            stack.enter_context(ctx)
        out = await _pdf_reader.read_pdf_as_content_blocks(
            "/tmp/probe.pdf",
            AsyncMock(),
            supports_vision=False,
            vision_fallback_model_cfg={"model": "gpt-4o-mini", "api_key": "test"},
        )

    text = "".join(dict(b).get("text", "") for b in out) if isinstance(out, list) else str(out)
    for page in (4, 5, 6, 7, 8):
        assert f"[Page {page}]" in text
    assert "[Page 1]" not in text


@pytest.mark.asyncio
async def test_pdf_without_any_vision_route_stays_plain_text():
    """No vision support and no fallback chain: the reader must not build a vision engine."""
    from myrm_agent_harness.agent.meta_tools.file_ops.utils import pdf_reader as _pdf_reader

    result = _pdf_extract_result(text="body text", page_numbers=[1])

    with (
        _patch_extract(result),
        patch("os.unlink"),
        patch(
            "myrm_agent_harness.toolkits.file_parsers.pdf.pdf_content_extractor.extract_pdf_content",
            new=AsyncMock(return_value=result),
        ),
        patch(
            "myrm_agent_harness.toolkits.llms.vision.fallback_engine.create_vision_fallback_engine",
            side_effect=AssertionError("must not build a vision engine without a vision route"),
        ),
    ):
        out = await _pdf_reader.read_pdf_as_content_blocks(
            "/tmp/probe.pdf",
            AsyncMock(),
            supports_vision=False,
        )

    assert isinstance(out, str)
    assert "body text" in out


@pytest.mark.asyncio
async def test_text_mode_keeps_pdf_text_when_the_reader_returns_blocks():
    """The text-mode path must not drop a PDF just because a vision chain turned it into blocks.

    Regression: it only appended the result when it was a ``str``, so with an auxiliary chain
    configured the whole document vanished from the text parts.
    """
    from myrm_agent_harness.agent.meta_tools.file_ops.core import file_read_handlers as _handlers

    blocks = [
        {"type": "text", "text": "[PDF: /tmp/probe.pdf]\nbody"},
        {"type": "text", "text": "[PDF page analysis]\n[Page 2]\nscanned"},
    ]
    parts: list[str] = []

    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.core.file_read_handlers.read_pdf_as_content_blocks",
        new=AsyncMock(return_value=blocks),
    ):
        await _handlers.append_media_text_parts(
            parts,
            image_paths=[],
            pdf_paths=["/tmp/probe.pdf"],
            document_paths=[],
            video_paths=[],
            executor=AsyncMock(),
            supports_vision=False,
            vision_fallback_model_cfg={"model": "gpt-4o-mini", "api_key": "test"},
            vision_fallback_model_cfgs=None,
            parse_mode=None,
        )

    assert parts == ["[PDF: /tmp/probe.pdf]\nbody", "[PDF page analysis]\n[Page 2]\nscanned"]
