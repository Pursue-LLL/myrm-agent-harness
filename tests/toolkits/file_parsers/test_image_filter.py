import base64
import io

from PIL import Image, ImageDraw

from myrm_agent_harness.toolkits.file_parsers.image_filter import ImageAblationFilter


def create_b64_image(width: int, height: int, color: str = "white") -> str:
    """Helper to create test images."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _create_multicolor_b64() -> str:
    """Create a multi-color image that passes all heuristic filters."""
    img = Image.new("RGB", (200, 200), color="white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 100, 200], fill="red")
    draw.rectangle([100, 0, 200, 200], fill="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_image_filter_keeps_valid_image():
    """Test that a valid image is kept."""
    valid_img = _create_multicolor_b64()

    filter_svc = ImageAblationFilter()
    kept, trace = filter_svc.filter_images([valid_img])

    assert len(kept) == 1
    assert trace.kept_count == 1
    assert trace.dropped_count == 0


def test_image_filter_drops_small_icon():
    """Test that extremely tiny images like tracking pixels are dropped."""
    tiny_img = create_b64_image(10, 10)
    filter_svc = ImageAblationFilter()
    kept, trace = filter_svc.filter_images([tiny_img])

    assert len(kept) == 0
    assert trace.dropped_count == 1
    assert trace.drop_reasons.get("size_too_small") == 1


def test_image_filter_drops_aspect_ratio_outliers():
    """Test that horizontal lines or vertical banners are dropped."""
    # Ratio > 12
    line_img = create_b64_image(1000, 50, color="green")
    filter_svc = ImageAblationFilter()
    kept, trace = filter_svc.filter_images([line_img])

    assert len(kept) == 0
    assert trace.dropped_count == 1
    assert trace.drop_reasons.get("extreme_aspect_ratio") == 1


def test_image_filter_drops_monochrome():
    """Test that large completely white/black/solid color images are dropped."""
    blank_img = create_b64_image(500, 500, color="white")
    filter_svc = ImageAblationFilter()
    kept, trace = filter_svc.filter_images([blank_img])

    assert len(kept) == 0
    assert trace.dropped_count == 1
    assert trace.drop_reasons.get("monochrome_or_blank") == 1


def test_image_filter_dedups_identical_images():
    """Test that caching prevents identical images from passing twice."""
    valid_img = _create_multicolor_b64()

    filter_svc = ImageAblationFilter()
    kept, trace = filter_svc.filter_images([valid_img, valid_img, valid_img])

    assert len(kept) == 1
    assert trace.kept_count == 1
    assert trace.dropped_count == 2
    assert trace.drop_reasons.get("duplicate_cached") == 2


def test_image_filter_handles_invalid_base64():
    """Test resilience against broken strings."""
    filter_svc = ImageAblationFilter()
    kept, trace = filter_svc.filter_images(["not_valid_base64__&&"])

    assert len(kept) == 0
    assert trace.dropped_count == 1
    assert trace.drop_reasons.get("invalid_image") == 1


def test_image_filter_empty_list():
    """Test that empty input returns empty output."""
    filter_svc = ImageAblationFilter()
    kept, trace = filter_svc.filter_images([])

    assert len(kept) == 0
    assert trace.total_processed == 0
    assert trace.kept_count == 0
    assert trace.dropped_count == 0
