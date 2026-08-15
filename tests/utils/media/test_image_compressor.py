import io

import pytest
from PIL import Image

from myrm_agent_harness.utils.media.image_compressor import (
    SEND_COMPRESS_MAX_DIMENSION,
    ImageCompressor,
)


@pytest.fixture
def compressor():
    return ImageCompressor()


def create_test_image(width: int, height: int, format: str = "JPEG") -> io.BytesIO:
    img = Image.new("RGB", (width, height), color="red")
    buffer = io.BytesIO()
    img.save(buffer, format=format)
    buffer.seek(0)
    return buffer


def _make_jpeg_bytes(width: int, height: int) -> bytes:
    """Generate JPEG bytes of specified dimensions."""
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def test_compress_resize_jpeg(compressor):
    # Create a 4000x4000 image
    img_buffer = create_test_image(4000, 4000, "JPEG")

    # Compress with max_dimension=2048
    compressed_bytes = compressor.compress(img_buffer, quality=0.8, max_dimension=2048)
    assert compressed_bytes is not None

    # Verify dimensions
    result_img = Image.open(io.BytesIO(compressed_bytes))
    assert result_img.size == (2048, 2048)


def test_compress_no_resize_needed(compressor):
    # Create a 1000x1000 image
    img_buffer = create_test_image(1000, 1000, "JPEG")

    # Compress with max_dimension=2048
    compressed_bytes = compressor.compress(img_buffer, quality=0.8, max_dimension=2048)
    assert compressed_bytes is not None

    # Verify dimensions are unchanged
    result_img = Image.open(io.BytesIO(compressed_bytes))
    assert result_img.size == (1000, 1000)


def test_compress_resize_png(compressor):
    # Create a 3000x2000 PNG image
    img_buffer = create_test_image(3000, 2000, "PNG")

    # Compress with max_dimension=1500
    compressed_bytes = compressor.compress(img_buffer, quality=0.8, max_dimension=1500)
    assert compressed_bytes is not None

    # Verify dimensions (ratio should be preserved: 1500x1000)
    result_img = Image.open(io.BytesIO(compressed_bytes))
    assert result_img.size == (1500, 1000)


def test_compress_without_max_dimension(compressor):
    # Create a 3000x3000 image
    img_buffer = create_test_image(3000, 3000, "JPEG")

    # Compress with max_dimension=None
    compressed_bytes = compressor.compress(img_buffer, quality=0.8, max_dimension=None)
    assert compressed_bytes is not None

    # Verify dimensions are unchanged
    result_img = Image.open(io.BytesIO(compressed_bytes))
    assert result_img.size == (3000, 3000)


def test_png_tempfile_cleaned_on_compress_failure(compressor, monkeypatch, tmp_path):
    """PNG compression must not leak its temporary file when the pipeline raises."""
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(
        compressor,
        "_compress_png",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    png = create_test_image(64, 64, "PNG").getvalue()

    with pytest.raises(RuntimeError):
        compressor.compress(io.BytesIO(png))

    assert list(tmp_path.iterdir()) == []


def _make_gif_bytes(width: int = 64, height: int = 64, frames: int = 2) -> bytes:
    """Generate an (animated when frames > 1) GIF byte string."""
    images = [
        Image.new("RGB", (width, height), color=(i * 60, 100, 200))
        for i in range(frames)
    ]
    buf = io.BytesIO()
    images[0].save(
        buf, format="GIF", save_all=True, append_images=images[1:], duration=100, loop=0
    )
    return buf.getvalue()


def _make_webp_bytes(width: int = 64, height: int = 64, frames: int = 2) -> bytes:
    """Generate an (animated when frames > 1) WebP byte string."""
    images = [
        Image.new("RGB", (width, height), color=(i * 60, 100, 200))
        for i in range(frames)
    ]
    buf = io.BytesIO()
    images[0].save(
        buf,
        format="WEBP",
        save_all=True,
        append_images=images[1:],
        duration=100,
        loop=0,
    )
    return buf.getvalue()


class TestCompressIfNeeded:
    """Unit tests for responsive send-time compression."""

    def test_small_image_passes_through(self, compressor):
        raw = _make_jpeg_bytes(800, 600)
        result = compressor.compress_if_needed(raw)
        assert result is raw

    def test_dimension_oversized_compressed(self, compressor):
        raw = _make_jpeg_bytes(6000, 4000)
        result = compressor.compress_if_needed(raw)
        assert result is not raw
        assert len(result) < len(raw)
        img = Image.open(io.BytesIO(result))
        assert max(img.size) <= SEND_COMPRESS_MAX_DIMENSION

    def test_oversized_by_bytes_only_compressed(self, compressor):
        # Byte-overflow path: a lowered trigger threshold makes this JPEG exceed
        # it while its dimensions stay within max_dimension.
        raw = _make_jpeg_bytes(1024, 1024)
        result = compressor.compress_if_needed(
            raw, trigger_bytes=512, max_dimension=4096
        )
        assert result is not raw
        assert len(result) < len(raw)

    def test_animated_gif_preserved(self, compressor):
        raw = _make_gif_bytes(frames=3)
        result = compressor.compress_if_needed(raw)
        assert result is raw

    def test_animated_webp_preserved(self, compressor):
        raw = _make_webp_bytes(frames=3)
        result = compressor.compress_if_needed(raw)
        assert result is raw

    def test_static_gif_can_compress(self, compressor):
        raw = _make_gif_bytes(frames=1)
        result = compressor.compress_if_needed(raw)
        assert result == raw

    def test_corrupt_bytes_fallback_to_original(self, compressor):
        raw = b"not an image at all"
        result = compressor.compress_if_needed(raw)
        assert result is raw

    def test_empty_bytes_passthrough(self, compressor):
        raw = b""
        result = compressor.compress_if_needed(raw)
        assert result == raw

    def test_compression_no_smaller_fallback_to_original(self, compressor, monkeypatch):
        raw = _make_jpeg_bytes(6000, 4000)
        with monkeypatch.context() as m:
            m.setattr(compressor, "compress", lambda *a, **kw: raw)
            assert compressor.compress_if_needed(raw) is raw

    def test_output_format_forced(self, compressor):
        raw = _make_jpeg_bytes(6000, 4000)
        result = compressor.compress_if_needed(raw, output_format="webp")
        img = Image.open(io.BytesIO(result))
        assert img.format == "WEBP"
