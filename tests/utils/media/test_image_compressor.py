import io

import pytest
from PIL import Image

from myrm_agent_harness.utils.media.image_compressor import ImageCompressor


@pytest.fixture
def compressor():
    return ImageCompressor()

def create_test_image(width: int, height: int, format: str = "JPEG") -> io.BytesIO:
    img = Image.new("RGB", (width, height), color="red")
    buffer = io.BytesIO()
    img.save(buffer, format=format)
    buffer.seek(0)
    return buffer

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
