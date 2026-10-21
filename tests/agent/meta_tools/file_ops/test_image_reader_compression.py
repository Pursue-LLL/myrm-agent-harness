"""Tests for image_reader reactive compression logic.

Covers the three-tier threshold strategy:
- <= 5MB: raw base64 direct transfer (zero-loss)
- 5MB to 20MB: reactive compress to JPEG 4096px
- > 20MB: degrade to text placeholder
"""

from __future__ import annotations

import base64
import io
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from myrm_agent_harness.agent.meta_tools.file_ops.utils.image_reader import (
    _INLINE_THRESHOLD,
    _needs_compression,
    _reactive_compress,
    is_image_path,
    read_image_as_content_blocks,
)


def _make_jpeg_bytes(width: int, height: int, quality: int = 95) -> bytes:
    """Generate JPEG bytes of specified dimensions."""
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _make_png_bytes(width: int, height: int) -> bytes:
    """Generate PNG bytes of specified dimensions."""
    img = Image.new("RGBA", (width, height), color=(100, 150, 200, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestReactiveCompress:
    """Unit tests for _reactive_compress."""

    def test_small_image_passes_through(self) -> None:
        raw = _make_jpeg_bytes(800, 600)
        result = _reactive_compress(raw)
        assert result is not None
        img = Image.open(io.BytesIO(result))
        assert img.format == "JPEG"
        assert img.size == (800, 600)

    def test_large_image_resized_to_4096(self) -> None:
        raw = _make_jpeg_bytes(6000, 4000)
        result = _reactive_compress(raw)
        assert result is not None
        img = Image.open(io.BytesIO(result))
        assert img.format == "JPEG"
        assert max(img.size) <= 4096
        assert img.size == (4096, 2730)

    def test_png_converted_to_jpeg(self) -> None:
        raw = _make_png_bytes(2000, 1500)
        result = _reactive_compress(raw)
        assert result is not None
        img = Image.open(io.BytesIO(result))
        assert img.format == "JPEG"
        assert img.mode == "RGB"

    def test_rgba_transparency_handled(self) -> None:
        img = Image.new("RGBA", (100, 100), (255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result = _reactive_compress(buf.getvalue())
        assert result is not None
        out = Image.open(io.BytesIO(result))
        assert out.mode == "RGB"

    def test_corrupt_data_returns_none(self) -> None:
        result = _reactive_compress(b"not an image at all")
        assert result is None

    def test_tall_image_resized_by_height(self) -> None:
        raw = _make_jpeg_bytes(2000, 8000)
        result = _reactive_compress(raw)
        assert result is not None
        img = Image.open(io.BytesIO(result))
        assert img.size[1] <= 4096
        assert img.size == (1024, 4096)


class TestReadImageThresholdStrategy:
    """Integration tests for the three-tier threshold in read_image_as_content_blocks."""

    @pytest.mark.asyncio
    async def test_small_image_zero_loss(self) -> None:
        """Images <= 5MB should transfer raw base64 without compression."""
        small_bytes = _make_jpeg_bytes(1920, 1080)
        assert len(small_bytes) < _INLINE_THRESHOLD

        executor = AsyncMock()
        executor.read_file_bytes.return_value = small_bytes

        result = await read_image_as_content_blocks("test.jpg", executor, True)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[1]["type"] in ("image", "image_url")
        b64_str = (
            result[1].get("base64")
            or result[1].get("data")
            or result[1].get("image_url", {}).get("url", "").split(",")[-1]
        )
        decoded = base64.b64decode(b64_str)
        assert decoded == small_bytes

    @pytest.mark.asyncio
    async def test_medium_image_compressed(self) -> None:
        """Images between 5-20MB should be reactively compressed."""
        medium_bytes = b"\x00" * (6 * 1024 * 1024)

        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.image_reader._ladder_compress"
        ) as mock_compress:
            fake_jpeg = _make_jpeg_bytes(4096, 3000)
            mock_compress.return_value = (fake_jpeg, (4096, 3000))

            executor = AsyncMock()
            executor.read_file_bytes.return_value = medium_bytes

            result = await read_image_as_content_blocks("big.png", executor, True)
            mock_compress.assert_called_once_with(medium_bytes)
            assert isinstance(result, list)
            assert "image/jpeg" in result[0]["text"]

    @pytest.mark.asyncio
    async def test_oversized_image_degrades_to_text(self) -> None:
        """Images > 50MB should degrade to text placeholder immediately."""
        huge_bytes = b"\x00" * (51 * 1024 * 1024)

        executor = AsyncMock()
        executor.read_file_bytes.return_value = huge_bytes

        result = await read_image_as_content_blocks("huge.png", executor, True)
        assert isinstance(result, str)
        assert "Exceeds" in result
        assert "limit for reading into memory" in result

    @pytest.mark.asyncio
    async def test_oversized_payload_degrades_to_text(self) -> None:
        """Images that are still > 20MB after compression should degrade."""
        medium_bytes = b"\x00" * (6 * 1024 * 1024)

        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.image_reader._ladder_compress"
        ) as mock_compress:
            fake_huge_jpeg = b"\x00" * (21 * 1024 * 1024)
            mock_compress.return_value = (fake_huge_jpeg, (4096, 4096))

            executor = AsyncMock()
            executor.read_file_bytes.return_value = medium_bytes

            result = await read_image_as_content_blocks("big.png", executor, True)
            mock_compress.assert_called_once()
            assert isinstance(result, str)
            assert "API payload limit" in result
        assert "bash_code_execute_tool" in result

    @pytest.mark.asyncio
    async def test_compression_failure_falls_back_to_text(self) -> None:
        """If reactive compression fails, degrade gracefully."""
        bad_bytes = b"\x89PNG" + b"\x00" * (6 * 1024 * 1024)

        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.utils.image_reader._ladder_compress",
            return_value=None,
        ):
            executor = AsyncMock()
            executor.read_file_bytes.return_value = bad_bytes

            result = await read_image_as_content_blocks("bad.png", executor, True)
            assert isinstance(result, str)
            assert "Compression failed" in result

    @pytest.mark.asyncio
    async def test_no_vision_returns_text(self) -> None:
        """Without vision support, any image returns text description."""
        small_bytes = _make_jpeg_bytes(100, 100)
        executor = AsyncMock()
        executor.read_file_bytes.return_value = small_bytes

        result = await read_image_as_content_blocks("x.jpg", executor, False)
        assert isinstance(result, str)
        assert "does not support vision" in result


class TestImageReaderEdgeBranches:
    """Path detection, read-failure fallback, and probe-failure branches."""

    def test_is_image_path_true(self) -> None:
        assert is_image_path("photo.PNG")
        assert is_image_path("sub/dir/pic.jpg")
        assert not is_image_path("notes.txt")

    @pytest.mark.asyncio
    async def test_read_failure_returns_text(self) -> None:
        executor = AsyncMock()
        executor.read_file_bytes.side_effect = RuntimeError("io error")

        result = await read_image_as_content_blocks("x.jpg", executor, True)
        assert isinstance(result, str)
        assert "Failed to read" in result

    @pytest.mark.asyncio
    async def test_file_not_found_reraises(self) -> None:
        executor = AsyncMock()
        executor.read_file_bytes.side_effect = FileNotFoundError("gone")

        with pytest.raises(FileNotFoundError):
            await read_image_as_content_blocks("x.jpg", executor, True)

    def test_needs_compression_probe_failure_is_false(self) -> None:
        assert _needs_compression(b"not an image at all") is False

    def test_needs_compression_dimension_trigger(self) -> None:
        raw = _make_jpeg_bytes(5000, 4000)
        assert len(raw) <= _INLINE_THRESHOLD
        assert _needs_compression(raw) is True

    def test_needs_compression_small_passthrough(self) -> None:
        raw = _make_jpeg_bytes(800, 600)
        assert _needs_compression(raw) is False


class TestLadderAndCoordinateDisclosure:
    """Verify Quality Ladder progressive compression and coordinate scale factor reporting."""

    @pytest.mark.asyncio
    async def test_coordinate_scale_factor_in_header(self) -> None:
        raw_large = _make_jpeg_bytes(6000, 4000)
        executor = AsyncMock()
        executor.read_file_bytes.return_value = raw_large

        result = await read_image_as_content_blocks("ultra.jpg", executor, True)
        assert isinstance(result, list)
        desc = result[0]["text"]
        assert "original: 6000x4000" in desc
        assert "attached: 4096x2730" in desc
        assert "scale: 0.6827" in desc
        assert "image/jpeg" in desc
