"""Integration tests for AccurateComparator with real browser execution.

Tests the actual JavaScript pixel comparison code in a real browser environment.
"""

import base64
import io

import pytest
from PIL import Image

from myrm_agent_harness.toolkits.browser.diff import AccurateComparator
from myrm_agent_harness.toolkits.browser.pool.browser_pool import ContextType, GlobalBrowserPool


def create_solid_image(width: int, height: int, color: tuple[int, int, int]) -> str:
    """Create a solid color image and return as base64."""
    img = Image.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def create_gradient_image(width: int, height: int) -> str:
    """Create a horizontal gradient image (black to white)."""
    img = Image.new("RGB", (width, height))
    pixels = img.load()
    for x in range(width):
        gray = int((x / width) * 255)
        for y in range(height):
            pixels[x, y] = (gray, gray, gray)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def create_text_image(width: int, height: int, text: str) -> str:
    """Create an image with text."""
    from PIL import ImageDraw, ImageFont

    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 40)
    except Exception:
        font = ImageFont.load_default()
    draw.text((10, 10), text, fill=(0, 0, 0), font=font)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


@pytest.mark.slow
@pytest.mark.asyncio
class TestAccurateComparatorIntegration:
    """Integration tests with real browser execution."""

    async def test_identical_solid_images(self) -> None:
        """Test comparison of two identical solid color images."""
        pool = GlobalBrowserPool()
        try:
            await pool.warmup(browsers=1, pages_per_context=1)
            page, ctx_key = await pool.acquire_page(ContextType.AGENT)
            context = page.context

            comparator = AccurateComparator()
            img = create_solid_image(100, 100, (255, 0, 0))

            result = await comparator.compare(context, img, img)

            assert result.similarity >= 0.99
            assert result.mismatch_percentage < 1.0
            assert not result.is_significant_change
            assert not result.dimension_mismatch
            assert result.algorithm == "canvas_pixel"

            await pool.release_page(page, ctx_key)
        finally:
            await pool.shutdown()

    async def test_different_solid_colors(self) -> None:
        """Test comparison of images with different solid colors."""
        pool = GlobalBrowserPool()
        try:
            await pool.warmup(browsers=1, pages_per_context=1)
            page, ctx_key = await pool.acquire_page(ContextType.AGENT)
            context = page.context

            comparator = AccurateComparator(mismatch_threshold=5.0)
            img1 = create_solid_image(100, 100, (255, 0, 0))
            img2 = create_solid_image(100, 100, (0, 0, 255))

            result = await comparator.compare(context, img1, img2)

            assert result.similarity < 0.5
            assert result.mismatch_percentage > 50.0
            assert result.is_significant_change
            assert not result.dimension_mismatch
            assert len(result.diff_image_b64) > 0

            await pool.release_page(page, ctx_key)
        finally:
            await pool.shutdown()

    async def test_dimension_mismatch_real(self) -> None:
        """Test comparison of images with different dimensions."""
        pool = GlobalBrowserPool()
        try:
            await pool.warmup(browsers=1, pages_per_context=1)
            page, ctx_key = await pool.acquire_page(ContextType.AGENT)
            context = page.context

            comparator = AccurateComparator()
            img1 = create_solid_image(100, 100, (255, 0, 0))
            img2 = create_solid_image(200, 200, (255, 0, 0))

            result = await comparator.compare(context, img1, img2)

            assert result.dimension_mismatch
            assert result.mismatch_percentage == 100.0
            assert result.is_significant_change

            await pool.release_page(page, ctx_key)
        finally:
            await pool.shutdown()

    async def test_gradient_images(self) -> None:
        """Test comparison of gradient images."""
        pool = GlobalBrowserPool()
        try:
            await pool.warmup(browsers=1, pages_per_context=1)
            page, ctx_key = await pool.acquire_page(ContextType.AGENT)
            context = page.context

            comparator = AccurateComparator()
            img1 = create_gradient_image(200, 100)
            img2 = create_gradient_image(200, 100)

            result = await comparator.compare(context, img1, img2)

            assert result.similarity >= 0.95
            assert result.mismatch_percentage < 5.0
            assert not result.is_significant_change

            await pool.release_page(page, ctx_key)
        finally:
            await pool.shutdown()

    async def test_text_images_identical(self) -> None:
        """Test comparison of images with identical text."""
        pool = GlobalBrowserPool()
        try:
            await pool.warmup(browsers=1, pages_per_context=1)
            page, ctx_key = await pool.acquire_page(ContextType.AGENT)
            context = page.context

            comparator = AccurateComparator()
            img1 = create_text_image(300, 100, "Hello World")
            img2 = create_text_image(300, 100, "Hello World")

            result = await comparator.compare(context, img1, img2)

            assert result.similarity >= 0.90
            assert result.mismatch_percentage < 10.0

            await pool.release_page(page, ctx_key)
        finally:
            await pool.shutdown()

    async def test_text_images_different(self) -> None:
        """Test comparison of images with different text."""
        pool = GlobalBrowserPool()
        try:
            await pool.warmup(browsers=1, pages_per_context=1)
            page, ctx_key = await pool.acquire_page(ContextType.AGENT)
            context = page.context

            comparator = AccurateComparator()
            img1 = create_text_image(300, 100, "Hello World")
            img2 = create_text_image(300, 100, "Goodbye World")

            result = await comparator.compare(context, img1, img2)

            assert result.mismatch_percentage > 0.0
            assert len(result.diff_image_b64) > 0

            await pool.release_page(page, ctx_key)
        finally:
            await pool.shutdown()

    async def test_color_tolerance_parameter(self) -> None:
        """Test that color_tolerance parameter affects results."""
        pool = GlobalBrowserPool()
        try:
            await pool.warmup(browsers=1, pages_per_context=1)
            page, ctx_key = await pool.acquire_page(ContextType.AGENT)
            context = page.context

            img1 = create_solid_image(100, 100, (100, 100, 100))
            img2 = create_solid_image(100, 100, (105, 105, 105))

            strict_comparator = AccurateComparator(color_tolerance=0.01)
            strict_result = await strict_comparator.compare(context, img1, img2)

            lenient_comparator = AccurateComparator(color_tolerance=0.5)
            lenient_result = await lenient_comparator.compare(context, img1, img2)

            assert strict_result.mismatch_percentage > lenient_result.mismatch_percentage

            await pool.release_page(page, ctx_key)
        finally:
            await pool.shutdown()

    async def test_mismatch_threshold_parameter(self) -> None:
        """Test that mismatch_threshold affects is_significant_change."""
        pool = GlobalBrowserPool()
        try:
            await pool.warmup(browsers=1, pages_per_context=1)
            page, ctx_key = await pool.acquire_page(ContextType.AGENT)
            context = page.context

            img1 = create_solid_image(100, 100, (255, 0, 0))
            Image.new("RGB", (100, 100), (255, 0, 0))
            draw = Image.new("RGB", (100, 100), (255, 0, 0))
            pixels = draw.load()
            for x in range(10):
                for y in range(10):
                    pixels[x, y] = (0, 0, 255)
            buffer = io.BytesIO()
            draw.save(buffer, format="PNG")
            img2 = base64.b64encode(buffer.getvalue()).decode("utf-8")

            strict_comparator = AccurateComparator(mismatch_threshold=0.5, color_tolerance=0.01)
            strict_result = await strict_comparator.compare(context, img1, img2)

            lenient_comparator = AccurateComparator(mismatch_threshold=5.0, color_tolerance=0.01)
            lenient_result = await lenient_comparator.compare(context, img1, img2)

            assert strict_result.is_significant_change
            assert not lenient_result.is_significant_change
            assert strict_result.mismatch_percentage == lenient_result.mismatch_percentage

            await pool.release_page(page, ctx_key)
        finally:
            await pool.shutdown()

    async def test_antialiasing_detection(self) -> None:
        """Test that include_aa parameter works."""
        pool = GlobalBrowserPool()
        try:
            await pool.warmup(browsers=1, pages_per_context=1)
            page, ctx_key = await pool.acquire_page(ContextType.AGENT)
            context = page.context

            img1 = create_solid_image(100, 100, (255, 255, 255))
            img2 = create_solid_image(100, 100, (254, 254, 254))

            with_aa = AccurateComparator(include_aa=True, color_tolerance=0.01)
            result_with_aa = await with_aa.compare(context, img1, img2)

            without_aa = AccurateComparator(include_aa=False, color_tolerance=0.01)
            result_without_aa = await without_aa.compare(context, img1, img2)

            assert result_with_aa.different_pixels <= result_without_aa.different_pixels

            await pool.release_page(page, ctx_key)
        finally:
            await pool.shutdown()

    async def test_performance_benchmark(self) -> None:
        """Test that comparison completes within expected time (~100ms)."""
        import time

        pool = GlobalBrowserPool()
        try:
            await pool.warmup(browsers=1, pages_per_context=1)
            page, ctx_key = await pool.acquire_page(ContextType.AGENT)
            context = page.context

            comparator = AccurateComparator()
            img1 = create_solid_image(800, 600, (255, 0, 0))
            img2 = create_solid_image(800, 600, (0, 255, 0))

            start = time.perf_counter()
            result = await comparator.compare(context, img1, img2)
            elapsed_ms = (time.perf_counter() - start) * 1000

            assert elapsed_ms < 2000  # includes cold-start browser overhead
            assert result.total_pixels == 800 * 600

            await pool.release_page(page, ctx_key)
        finally:
            await pool.shutdown()

    async def test_large_image_handling(self) -> None:
        """Test comparison of large images (1920x1080)."""
        pool = GlobalBrowserPool()
        try:
            await pool.warmup(browsers=1, pages_per_context=1)
            page, ctx_key = await pool.acquire_page(ContextType.AGENT)
            context = page.context

            comparator = AccurateComparator()
            img1 = create_solid_image(1920, 1080, (100, 100, 100))
            img2 = create_solid_image(1920, 1080, (100, 100, 100))

            result = await comparator.compare(context, img1, img2)

            assert result.total_pixels == 1920 * 1080
            assert result.similarity >= 0.99

            await pool.release_page(page, ctx_key)
        finally:
            await pool.shutdown()

    async def test_diff_image_format(self) -> None:
        """Test that diff image is valid PNG."""
        pool = GlobalBrowserPool()
        try:
            await pool.warmup(browsers=1, pages_per_context=1)
            page, ctx_key = await pool.acquire_page(ContextType.AGENT)
            context = page.context

            comparator = AccurateComparator()
            img1 = create_solid_image(50, 50, (255, 0, 0))
            img2 = create_solid_image(50, 50, (0, 0, 255))

            result = await comparator.compare(context, img1, img2)

            diff_bytes = base64.b64decode(result.diff_image_b64)
            diff_img = Image.open(io.BytesIO(diff_bytes))

            assert diff_img.format == "PNG"
            assert diff_img.size == (50, 50)

            await pool.release_page(page, ctx_key)
        finally:
            await pool.shutdown()
