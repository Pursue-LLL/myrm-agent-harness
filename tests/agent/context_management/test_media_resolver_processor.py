"""Tests for MediaResolverProcessor — lazy image URL-to-base64 resolution."""

from __future__ import annotations

import base64
import io
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import HumanMessage
from PIL import Image

from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.media_resolver import (
    MediaResolverProcessor,
    _resolve_local_file,
)


def _make_context(messages: list) -> ProcessorContext:
    return ProcessorContext(messages=messages, user_query="test")


def _make_large_jpeg_bytes(width: int = 6000, height: int = 4000) -> bytes:
    """Generate an oversized JPEG (dimensions + bytes both exceed send limits)."""
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _make_bmp_bytes(width: int, height: int) -> bytes:
    """Generate a deterministic uncompressed BMP (raw size = w*h*3 + header)."""
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="BMP")
    return buf.getvalue()


def _img_url(url: str, text: str = "look") -> HumanMessage:
    """Create a HumanMessage with an image_url pointing to a non-base64 URL."""
    return HumanMessage(
        content=[
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": url, "detail": "auto"}},
        ]
    )


def _img_base64(text: str = "look") -> HumanMessage:
    """Create a HumanMessage with a base64 image_url (already resolved)."""
    return HumanMessage(
        content=[
            {"type": "text", "text": text},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,iVBOR", "detail": "auto"},
            },
        ]
    )


class TestMediaResolverProcessor:
    """Unit tests for MediaResolverProcessor."""

    @pytest.mark.asyncio
    async def test_noop_when_all_base64(self) -> None:
        """No resolution needed when all images are already base64."""
        proc = MediaResolverProcessor()
        ctx = _make_context([_img_base64()])
        result = await proc.process(ctx)

        url = result.messages[0].content[1]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")

    @pytest.mark.asyncio
    async def test_noop_when_no_images(self) -> None:
        """No resolution needed for text-only messages."""
        proc = MediaResolverProcessor()
        ctx = _make_context([HumanMessage(content="hello")])
        result = await proc.process(ctx)
        assert result.messages[0].content == "hello"

    @pytest.mark.asyncio
    async def test_resolves_local_file(self) -> None:
        """Local file:// URLs are resolved to base64."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
            f.write(raw)
            f.flush()
            path = f.name

        try:
            proc = MediaResolverProcessor()
            ctx = _make_context([_img_url(f"file://{path}")])
            result = await proc.process(ctx)

            url = result.messages[0].content[1]["image_url"]["url"]
            assert url.startswith("data:image/")
            assert ";base64," in url
        finally:
            Path(path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_resolves_bare_file_path(self) -> None:
        """Bare file paths (no scheme) are resolved as local files."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff" + b"\x00" * 100)
            f.flush()
            path = f.name

        try:
            proc = MediaResolverProcessor()
            ctx = _make_context([_img_url(path)])
            result = await proc.process(ctx)

            url = result.messages[0].content[1]["image_url"]["url"]
            assert url.startswith("data:image/")
        finally:
            Path(path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_resolves_api_path_via_reader(self) -> None:
        """API paths are resolved via injected file_content_reader."""
        raw_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        reader = AsyncMock(return_value=raw_bytes)

        proc = MediaResolverProcessor(file_content_reader=reader)
        ctx = _make_context([_img_url("/api/media/files/file_abc123/content")])
        result = await proc.process(ctx)

        url = result.messages[0].content[1]["image_url"]["url"]
        assert url.startswith("data:image/")
        reader.assert_awaited_once_with("file_abc123")

    @pytest.mark.asyncio
    async def test_mixed_base64_and_url(self) -> None:
        """Only non-base64 URLs are resolved; existing base64 is untouched."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            f.flush()
            path = f.name

        try:
            proc = MediaResolverProcessor()
            msg = HumanMessage(
                content=[
                    {"type": "text", "text": "compare"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,existing",
                            "detail": "auto",
                        },
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"file://{path}", "detail": "auto"},
                    },
                ]
            )
            ctx = _make_context([msg])
            result = await proc.process(ctx)

            content = result.messages[0].content
            assert content[1]["image_url"]["url"] == "data:image/png;base64,existing"
            assert content[2]["image_url"]["url"].startswith("data:image/")
            assert content[2]["image_url"]["url"] != f"file://{path}"
        finally:
            Path(path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_graceful_failure_preserves_url(self) -> None:
        """When resolution fails, the original URL is preserved (not crashed)."""
        proc = MediaResolverProcessor()
        ctx = _make_context([_img_url("file:///nonexistent/path/image.png")])
        result = await proc.process(ctx)

        url = result.messages[0].content[1]["image_url"]["url"]
        assert url == "file:///nonexistent/path/image.png"

    @pytest.mark.asyncio
    async def test_should_process_always_true(self) -> None:
        proc = MediaResolverProcessor()
        ctx = _make_context([])
        assert await proc.should_process(ctx) is True

    @pytest.mark.asyncio
    async def test_processor_name(self) -> None:
        proc = MediaResolverProcessor()
        assert proc.name == "media_resolver"


class TestResolveLocalFile:
    """Direct unit tests for _resolve_local_file helper."""

    def test_returns_data_url_for_valid_file(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
            f.write(raw)
            f.flush()
            path = f.name

        try:
            result = _resolve_local_file(path)
            assert result is not None
            assert result.startswith("data:image/")
            b64_part = result.split(";base64,")[1]
            decoded = base64.b64decode(b64_part)
            assert decoded == raw
        finally:
            Path(path).unlink(missing_ok=True)

    def test_returns_none_for_missing_file(self) -> None:
        result = _resolve_local_file("/tmp/definitely_not_exists_12345.png")
        assert result is None

    def test_returns_none_for_directory(self) -> None:
        result = _resolve_local_file("/tmp")
        assert result is None


class TestSendTimeCompression:
    """Send-time responsive compression applied during URL resolution."""

    @pytest.mark.asyncio
    async def test_oversized_local_file_compressed(self) -> None:
        """Oversized local images are downsampled before base64 encoding."""
        raw = _make_large_jpeg_bytes()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(raw)
            f.flush()
            path = f.name

        try:
            proc = MediaResolverProcessor()
            ctx = _make_context([_img_url(f"file://{path}")])
            result = await proc.process(ctx)

            url = result.messages[0].content[1]["image_url"]["url"]
            b64_part = url.split(";base64,")[1]
            decoded = base64.b64decode(b64_part)
            assert len(decoded) < len(raw)
            with Image.open(io.BytesIO(decoded)) as img:
                assert max(img.size) <= 2048
        finally:
            Path(path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_small_local_file_passes_through_unchanged(self) -> None:
        """Small local images bypass compression entirely."""
        raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(raw)
            f.flush()
            path = f.name

        try:
            proc = MediaResolverProcessor()
            ctx = _make_context([_img_url(f"file://{path}")])
            result = await proc.process(ctx)

            url = result.messages[0].content[1]["image_url"]["url"]
            b64_part = url.split(";base64,")[1]
            assert base64.b64decode(b64_part) == raw
        finally:
            Path(path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_base64_oversized_local_file_compressed(self) -> None:
        """Raw bytes under the 4 MiB trigger but base64 over it must still
        compress — real MediaResolver path exercises the base64-space check."""
        # 1100x1100 RGB BMP is deterministic: ~3.63 MiB raw (< 4 MiB) while
        # its base64 form is ~4.84 MiB (> 4 MiB); dimensions fit the 2048 cap.
        raw = _make_bmp_bytes(1100, 1100)
        assert len(raw) < 4 * 1024 * 1024
        assert 4 * ((len(raw) + 2) // 3) > 4 * 1024 * 1024

        with tempfile.NamedTemporaryFile(suffix=".bmp", delete=False) as f:
            f.write(raw)
            f.flush()
            path = f.name

        try:
            proc = MediaResolverProcessor()
            ctx = _make_context([_img_url(f"file://{path}")])
            result = await proc.process(ctx)

            url = result.messages[0].content[1]["image_url"]["url"]
            decoded = base64.b64decode(url.split(";base64,")[1])
            assert len(decoded) < len(raw)
        finally:
            Path(path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_api_path_compressed_via_reader(self) -> None:
        """Oversized images from the file_content_reader are compressed."""
        raw = _make_large_jpeg_bytes()
        reader = AsyncMock(return_value=raw)

        proc = MediaResolverProcessor(file_content_reader=reader)
        ctx = _make_context([_img_url("/api/media/files/file_abc123/content")])
        result = await proc.process(ctx)

        url = result.messages[0].content[1]["image_url"]["url"]
        decoded = base64.b64decode(url.split(";base64,")[1])
        assert len(decoded) < len(raw)
        reader.assert_awaited_once_with("file_abc123")

    @pytest.mark.asyncio
    async def test_animated_gif_api_path_preserved(self) -> None:
        """Animated GIFs from the reader keep their animation frames."""
        images = [
            Image.new("RGB", (64, 64), color=(255, 0, 0)),
            Image.new("RGB", (64, 64), color=(0, 255, 0)),
        ]
        buf = io.BytesIO()
        images[0].save(
            buf,
            format="GIF",
            save_all=True,
            append_images=images[1:],
            duration=100,
            loop=0,
        )
        gif_bytes = buf.getvalue()
        reader = AsyncMock(return_value=gif_bytes)

        proc = MediaResolverProcessor(file_content_reader=reader)
        ctx = _make_context([_img_url("/api/media/files/file_gif/content")])
        result = await proc.process(ctx)

        url = result.messages[0].content[1]["image_url"]["url"]
        decoded = base64.b64decode(url.split(";base64,")[1])
        assert decoded == gif_bytes


def test_internal_api_origin_uses_port_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from myrm_agent_harness.agent.context_management.pipeline.processors import (
        media_resolver,
    )

    monkeypatch.setenv("PORT", "9099")
    assert media_resolver._internal_api_origin() == "http://127.0.0.1:9099"
