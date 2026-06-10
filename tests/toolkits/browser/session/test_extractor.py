"""Unit tests for Extractor class."""

import base64
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from myrm_agent_harness.toolkits.browser.diff import (
    AccurateComparisonResult,
    FastComparisonResult,
)
from myrm_agent_harness.toolkits.browser.session.extractor import Extractor


def create_test_image(width: int = 100, height: int = 100, color: tuple[int, int, int] = (255, 0, 0)) -> str:
    """Create a solid color test image and return as base64."""
    img = Image.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


@pytest.fixture
def mock_page() -> MagicMock:
    """Create a mock Page object."""
    page = MagicMock()
    page.context = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"fake_screenshot_bytes")
    return page


@pytest.fixture
def extractor(mock_page: MagicMock) -> Extractor:
    """Create an Extractor instance with a mock page."""
    return Extractor(mock_page)


class TestExtractor:
    """Test suite for Extractor."""

    async def test_compare_screenshots_fast_strategy(self, extractor: Extractor) -> None:
        """Test compare_screenshots with fast strategy."""
        baseline = create_test_image()
        current_b64 = create_test_image()

        with patch.object(extractor, "extract_screenshot", return_value=current_b64):
            result = await extractor.compare_screenshots(baseline, strategy="fast")

        assert isinstance(result, FastComparisonResult)
        assert result.algorithm == "dhash"
        assert hasattr(result, "similarity")
        assert hasattr(result, "hamming_distance")

    async def test_compare_screenshots_accurate_strategy(self, extractor: Extractor) -> None:
        """Test compare_screenshots with accurate strategy."""
        baseline = create_test_image()
        current_b64 = create_test_image()

        # Mock the entire comparator to avoid complex context mocking
        mock_result = AccurateComparisonResult(
            algorithm="canvas_pixel",
            total_pixels=10000,
            different_pixels=0,
            mismatch_percentage=0.0,
            diff_image_b64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            dimension_mismatch=False,
            is_significant_change=False,
            similarity=1.0,
        )

        with (
            patch.object(extractor, "extract_screenshot", return_value=current_b64),
            patch.object(extractor._comparator, "compare", return_value=mock_result),
        ):
            result = await extractor.compare_screenshots(baseline, strategy="accurate")

        assert isinstance(result, AccurateComparisonResult)
        assert result.algorithm == "canvas_pixel"
        assert hasattr(result, "diff_image_b64")
        assert hasattr(result, "mismatch_percentage")

    async def test_compare_screenshots_invalid_strategy(self, extractor: Extractor) -> None:
        """Test compare_screenshots raises ValueError for invalid strategy."""
        baseline = create_test_image()

        with pytest.raises(ValueError, match="Invalid strategy: invalid"):
            await extractor.compare_screenshots(baseline, strategy="invalid")  # type: ignore[arg-type]

    async def test_extract_screenshot_with_retina(self, extractor: Extractor, mock_page: MagicMock) -> None:
        """Test extract_screenshot with retina mode."""
        test_bytes = b"screenshot_data"
        mock_page.screenshot.return_value = test_bytes
        mock_cdp = AsyncMock()
        mock_page.context.new_cdp_session.return_value = mock_cdp

        result = await extractor.extract_screenshot(retina=True)

        assert result == base64.b64encode(test_bytes).decode("utf-8")
        mock_page.screenshot.assert_called_once()
        assert mock_page.context.new_cdp_session.call_count == 2

    async def test_set_device_scale_factor_success(self, extractor: Extractor, mock_page: MagicMock) -> None:
        """Test _set_device_scale_factor sets DPR successfully."""
        mock_cdp = AsyncMock()
        mock_page.context.new_cdp_session.return_value = mock_cdp

        await extractor._set_device_scale_factor(2.0)

        mock_page.context.new_cdp_session.assert_called_once_with(mock_page)
        mock_cdp.send.assert_called_once()
        mock_cdp.detach.assert_called_once()

    async def test_set_device_scale_factor_handles_exception(self, extractor: Extractor, mock_page: MagicMock) -> None:
        """Test _set_device_scale_factor handles exceptions gracefully."""
        mock_page.context.new_cdp_session.side_effect = RuntimeError("CDP session failed")

        await extractor._set_device_scale_factor(2.0)

    async def test_extract_full_text(self, extractor: Extractor, mock_page: MagicMock) -> None:
        """Test extract_full_text retrieves page text with markdown conversion."""
        expected_text = "# Hello\n\nThis is test content."
        mock_frame = MagicMock()
        mock_frame.evaluate = AsyncMock(return_value=expected_text)
        mock_page.frames = [mock_frame]

        result = await extractor.extract_full_text()

        assert result == expected_text

    async def test_extract_full_text_with_selector(self, extractor: Extractor, mock_page: MagicMock) -> None:
        """Test extract_full_text with a CSS selector."""
        expected_text = "Targeted content"
        mock_frame = MagicMock()
        mock_frame.evaluate = AsyncMock(return_value=expected_text)
        mock_page.frames = [mock_frame]

        result = await extractor.extract_full_text(selector=".main-content")

        assert result == expected_text
        mock_frame.evaluate.assert_called_once()
        call_args = mock_frame.evaluate.call_args
        assert call_args[0][1] == ".main-content"

    async def test_extract_full_text_js_contains_shadow_dom_penetration(
        self, extractor: Extractor, mock_page: MagicMock
    ) -> None:
        """Verify the JS script used by extract_full_text includes Shadow DOM traversal."""
        mock_frame = MagicMock()
        mock_frame.evaluate = AsyncMock(return_value="")
        mock_page.frames = [mock_frame]

        await extractor.extract_full_text()

        js_script = mock_frame.evaluate.call_args[0][0]
        assert "node.shadowRoot" in js_script, "JS script must traverse node.shadowRoot for Shadow DOM penetration"
        assert "node.shadowRoot.childNodes" in js_script or "node.shadowRoot)" in js_script

    async def test_extract_full_text_multi_frame_with_shadow_dom(
        self, extractor: Extractor, mock_page: MagicMock
    ) -> None:
        """Test that extract_full_text processes multiple frames, each potentially containing Shadow DOM."""
        frame0 = MagicMock()
        frame0.evaluate = AsyncMock(return_value="Main frame content with shadow")
        frame1 = MagicMock()
        frame1.evaluate = AsyncMock(return_value="Iframe content")
        mock_page.frames = [frame0, frame1]

        result = await extractor.extract_full_text()

        assert "Main frame content with shadow" in result
        assert "Iframe content" in result
        assert "Frame 1" in result

    async def test_extract_full_text_frame_error_resilience(
        self, extractor: Extractor, mock_page: MagicMock
    ) -> None:
        """Test that a failing frame does not prevent extraction from other frames."""
        frame0 = MagicMock()
        frame0.evaluate = AsyncMock(return_value="Good frame")
        frame1 = MagicMock()
        frame1.evaluate = AsyncMock(side_effect=RuntimeError("Frame detached"))
        mock_page.frames = [frame0, frame1]

        result = await extractor.extract_full_text()

        assert "Good frame" in result

    async def test_export_pdf(self, extractor: Extractor, mock_page: MagicMock) -> None:
        """Test export_pdf saves page as PDF."""
        pdf_path = "/tmp/test.pdf"
        mock_page.pdf = AsyncMock()

        result = await extractor.export_pdf(pdf_path)

        assert "Exported PDF to" in result
        assert pdf_path in result
        mock_page.pdf.assert_called_once_with(path=pdf_path)

    async def test_detect_significant_visual_content_true(
        self, extractor: Extractor, mock_page: MagicMock
    ) -> None:
        """Test detect_significant_visual_content returns True when large Canvas exists."""
        mock_page.evaluate = AsyncMock(return_value=True)

        result = await extractor.detect_significant_visual_content()

        assert result is True

    async def test_detect_significant_visual_content_false(
        self, extractor: Extractor, mock_page: MagicMock
    ) -> None:
        """Test detect_significant_visual_content returns False when no large visual elements."""
        mock_page.evaluate = AsyncMock(return_value=False)

        result = await extractor.detect_significant_visual_content()

        assert result is False

    async def test_detect_significant_visual_content_error_resilience(
        self, extractor: Extractor, mock_page: MagicMock
    ) -> None:
        """Test detect_significant_visual_content returns False on evaluation error."""
        mock_page.evaluate = AsyncMock(side_effect=RuntimeError("Page crashed"))

        result = await extractor.detect_significant_visual_content()

        assert result is False

    async def test_extract_full_text_js_contains_svg_text_extraction(
        self, extractor: Extractor, mock_page: MagicMock
    ) -> None:
        """Verify JS script extracts text/tspan elements from SVG instead of skipping."""
        mock_frame = MagicMock()
        mock_frame.evaluate = AsyncMock(return_value="")
        mock_page.frames = [mock_frame]

        await extractor.extract_full_text()

        js_script = mock_frame.evaluate.call_args[0][0]
        assert "SVG" in js_script
        assert "text" in js_script and "tspan" in js_script
        assert "querySelectorAll" in js_script
        assert "[SVG:" in js_script or "SVG:" in js_script
