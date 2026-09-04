"""Tests for vision fallback engine and cache."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.core.config.llm import LLMConfig
from myrm_agent_harness.toolkits.llms.vision.cache import (
    build_cache_key,
    get_vision_cache_store,
)
from myrm_agent_harness.toolkits.llms.vision.fallback_engine import VisionFallbackEngine
from myrm_agent_harness.toolkits.llms.vision.types import (
    VisionBackendKind,
    VisionResult,
)


def _tiny_png() -> bytes:
    # 1x1 PNG
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


@pytest.fixture
def fallback_engine() -> VisionFallbackEngine:
    cfg = LLMConfig(model="test-vl", api_key="k", base_url="http://localhost")
    engine = VisionFallbackEngine(cfg)
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "together-answer"
    mock_model.ainvoke = AsyncMock(return_value=mock_response)
    engine._models = [mock_model]
    return engine


@pytest.mark.asyncio
async def test_describe_images_together_single_call(
    fallback_engine: VisionFallbackEngine,
) -> None:
    b64 = base64.b64encode(_tiny_png()).decode("ascii")
    result = await fallback_engine.describe_images_together(
        [(b64, "image/png")], "compare"
    )
    assert result == "together-answer"
    assert fallback_engine._models[0].ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_cache_key_isolated_by_task() -> None:
    store = get_vision_cache_store()
    store.clear()
    key_a = build_cache_key(content_hash="abc", mode="ocr", task="amount")
    key_b = build_cache_key(content_hash="abc", mode="ocr", task="date")
    store.set(key_a, VisionResult(text="a", backend_kind=VisionBackendKind.VLM))
    assert store.get(key_b) is None


def _tall_png(width: int = 200, height: int = 1200) -> bytes:
    from PIL import Image
    import io

    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_slice_long_image_if_needed() -> None:
    from myrm_agent_harness.utils.media.image_compressor import image_compressor

    # Normal ratio (not sliced)
    normal_bytes = _tiny_png()
    slices_normal = image_compressor.slice_long_image_if_needed(normal_bytes)
    assert len(slices_normal) == 1

    # Tall ratio (200x1200, ratio=6.0 > 1.8, height > 1000, sliced)
    tall_bytes = _tall_png(200, 1200)
    slices_tall = image_compressor.slice_long_image_if_needed(
        tall_bytes, aspect_ratio_threshold=1.8, min_height_threshold=1000, max_dimension=800
    )
    assert len(slices_tall) > 1
    # Check that each slice is valid image bytes
    from PIL import Image
    import io

    for tile in slices_tall:
        tile_img = Image.open(io.BytesIO(tile))
        assert tile_img.width == 200
        assert tile_img.height <= 800

    # Mobile flagship ratio test: iPhone 14/15/16 Pro Max aspect ratio (e.g. 500 x 1100, ratio=2.2 > 1.8)
    mobile_bytes = _tall_png(500, 1100)
    slices_mobile = image_compressor.slice_long_image_if_needed(
        mobile_bytes, aspect_ratio_threshold=1.8, min_height_threshold=1000
    )
    assert len(slices_mobile) >= 2


@pytest.mark.asyncio
async def test_describe_image_b64_long_screenshot_slicing(
    fallback_engine: VisionFallbackEngine,
) -> None:
    tall_bytes = _tall_png(200, 1200)
    tall_b64 = base64.b64encode(tall_bytes).decode("ascii")

    res = await fallback_engine.describe_image_b64(tall_b64, mime_type="image/png")
    assert "### [Section 1/" in res
    assert "### [Section 2/" in res
    assert fallback_engine._models[0].ainvoke.await_count > 1


def test_slice_long_image_edge_cases() -> None:
    from myrm_agent_harness.utils.media.image_compressor import image_compressor

    # 1. Corrupted bytes fallback
    corrupt = b"not-a-valid-image-data-stream"
    assert image_compressor.slice_long_image_if_needed(corrupt) == [corrupt]

    # 2. Square image below ratio threshold (e.g. 1200x1200, ratio=1.0 < 1.8)
    square_bytes = _tall_png(1200, 1200)
    assert len(image_compressor.slice_long_image_if_needed(square_bytes)) == 1

    # 3. Tall ratio but height below min_height_threshold (e.g. 100x500, ratio=5.0 but height=500 <= 1000)
    short_bytes = _tall_png(100, 500)
    assert len(image_compressor.slice_long_image_if_needed(short_bytes, min_height_threshold=1000)) == 1

    # 4. Extreme long screenshot (200x4000) with custom tile height and overlap
    extreme_bytes = _tall_png(200, 4000)
    slices = image_compressor.slice_long_image_if_needed(
        extreme_bytes,
        max_dimension=1000,
        aspect_ratio_threshold=1.8,
        min_height_threshold=1000,
        overlap_pixels=80,
    )
    assert len(slices) >= 4


@pytest.mark.asyncio
async def test_describe_image_b64_single_image(
    fallback_engine: VisionFallbackEngine,
) -> None:
    # Tiny image should not be sliced
    tiny_b64 = base64.b64encode(_tiny_png()).decode("ascii")
    res = await fallback_engine.describe_image_b64(tiny_b64, mime_type="image/png")
    assert res == "together-answer"
    assert "### [Section" not in res


@pytest.mark.asyncio
async def test_describe_image_b64_slice_exception_fallback(
    fallback_engine: VisionFallbackEngine,
) -> None:
    from unittest.mock import patch

    tall_bytes = _tall_png(200, 1200)
    tall_b64 = base64.b64encode(tall_bytes).decode("ascii")

    with patch(
        "myrm_agent_harness.utils.media.image_compressor.image_compressor.slice_long_image_if_needed",
        side_effect=RuntimeError("Simulated slice decoder failure"),
    ):
        res = await fallback_engine.describe_image_b64(tall_b64, mime_type="image/png")
        assert res == "together-answer"
        assert "### [Section" not in res


@pytest.mark.asyncio
async def test_describe_image_b64_custom_prompt(
    fallback_engine: VisionFallbackEngine,
) -> None:
    tall_bytes = _tall_png(200, 1200)
    tall_b64 = base64.b64encode(tall_bytes).decode("ascii")

    res = await fallback_engine.describe_image_b64(
        tall_b64, mime_type="image/png", prompt="Extract financial summary table"
    )
    assert "### [Section 1/" in res
    call_args = fallback_engine._models[0].ainvoke.call_args[0][0]
    # Check that custom prompt was included in messages
    prompt_found = any(
        "Extract financial summary table" in str(msg.content)
        for msg in call_args
        if hasattr(msg, "content")
    )
    assert prompt_found




