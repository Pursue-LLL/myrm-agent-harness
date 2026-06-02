"""Unit tests for AccurateComparator (Canvas API pixel-level comparison)."""

import base64
import io
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from myrm_agent_harness.toolkits.browser.diff import AccurateComparator, AccurateComparisonResult


def create_test_image(width: int = 100, height: int = 100, color: tuple[int, int, int] = (255, 0, 0)) -> str:
    """Create a solid color test image and return as base64."""
    img = Image.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


class TestAccurateComparator:
    """Test suite for AccurateComparator."""

    def test_initialization_default_parameters(self) -> None:
        """Test initialization with default parameters."""
        comparator = AccurateComparator()
        assert comparator.color_tolerance == 0.1
        assert comparator.mismatch_threshold == 5.0

    def test_initialization_custom_parameters(self) -> None:
        """Test initialization with custom parameters."""
        comparator = AccurateComparator(color_tolerance=0.2, mismatch_threshold=10.0)
        assert comparator.color_tolerance == 0.2
        assert comparator.mismatch_threshold == 10.0

    def test_initialization_invalid_color_tolerance_too_low(self) -> None:
        """Test initialization fails with color_tolerance < 0."""
        with pytest.raises(ValueError, match="color_tolerance must be in"):
            AccurateComparator(color_tolerance=-0.1)

    def test_initialization_invalid_color_tolerance_too_high(self) -> None:
        """Test initialization fails with color_tolerance > 1."""
        with pytest.raises(ValueError, match="color_tolerance must be in"):
            AccurateComparator(color_tolerance=1.1)

    def test_initialization_invalid_mismatch_threshold_too_low(self) -> None:
        """Test initialization fails with mismatch_threshold < 0."""
        with pytest.raises(ValueError, match="mismatch_threshold must be in"):
            AccurateComparator(mismatch_threshold=-1.0)

    def test_initialization_invalid_mismatch_threshold_too_high(self) -> None:
        """Test initialization fails with mismatch_threshold > 100."""
        with pytest.raises(ValueError, match="mismatch_threshold must be in"):
            AccurateComparator(mismatch_threshold=101.0)

    @pytest.mark.asyncio
    async def test_compare_identical_images(self) -> None:
        """Test comparison of two identical images."""
        comparator = AccurateComparator()
        img_b64 = create_test_image(color=(100, 150, 200))

        mock_context = MagicMock()
        mock_page = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_page.route = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock(
            return_value={
                "totalPixels": 10000,
                "differentPixels": 0,
                "mismatchPercentage": 0.0,
                "diffBase64": "base64_string",
                "dimensionMismatch": False,
            }
        )
        mock_page.unroute = AsyncMock()
        mock_page.close = AsyncMock()

        result = await comparator.compare(mock_context, img_b64, img_b64)

        assert isinstance(result, AccurateComparisonResult)
        assert result.similarity == 1.0
        assert result.total_pixels == 10000
        assert result.different_pixels == 0
        assert result.mismatch_percentage == 0.0
        assert result.is_significant_change is False
        assert result.dimension_mismatch is False
        assert result.algorithm == "canvas_pixel"
        assert len(result.diff_image_b64) > 0

    @pytest.mark.asyncio
    async def test_compare_different_images(self) -> None:
        """Test comparison of different images."""
        comparator = AccurateComparator(mismatch_threshold=5.0)
        img1 = create_test_image(color=(0, 0, 0))
        img2 = create_test_image(color=(255, 255, 255))

        mock_context = MagicMock()
        mock_page = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_page.route = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock(
            return_value={
                "totalPixels": 10000,
                "differentPixels": 8500,
                "mismatchPercentage": 85.0,
                "diffBase64": "base64_diff_string",
                "dimensionMismatch": False,
            }
        )
        mock_page.unroute = AsyncMock()
        mock_page.close = AsyncMock()

        result = await comparator.compare(mock_context, img1, img2)

        assert pytest.approx(result.similarity, rel=1e-9) == 0.15
        assert result.total_pixels == 10000
        assert result.different_pixels == 8500
        assert result.mismatch_percentage == 85.0
        assert result.is_significant_change is True
        assert result.dimension_mismatch is False

    @pytest.mark.asyncio
    async def test_compare_dimension_mismatch(self) -> None:
        """Test comparison of images with different dimensions."""
        comparator = AccurateComparator()
        img1 = create_test_image(width=100, height=100)
        img2 = create_test_image(width=200, height=200)

        mock_context = MagicMock()
        mock_page = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_page.route = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock(
            return_value={
                "totalPixels": 40000,
                "differentPixels": 40000,
                "mismatchPercentage": 100.0,
                "diffBase64": "base64_string",
                "dimensionMismatch": True,
            }
        )
        mock_page.unroute = AsyncMock()
        mock_page.close = AsyncMock()

        result = await comparator.compare(mock_context, img1, img2)

        assert result.dimension_mismatch is True
        assert result.mismatch_percentage == 100.0
        assert result.is_significant_change is True

    @pytest.mark.asyncio
    async def test_compare_threshold_boundary(self) -> None:
        """Test is_significant_change threshold boundary detection."""
        comparator = AccurateComparator(mismatch_threshold=5.0)
        img1 = create_test_image()
        img2 = create_test_image()

        mock_context = MagicMock()
        mock_page = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_page.route = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock(
            return_value={
                "totalPixels": 10000,
                "differentPixels": 500,
                "mismatchPercentage": 5.0,
                "diffBase64": "base64_string",
                "dimensionMismatch": False,
            }
        )
        mock_page.unroute = AsyncMock()
        mock_page.close = AsyncMock()

        result = await comparator.compare(mock_context, img1, img2)

        assert result.mismatch_percentage == 5.0
        assert result.is_significant_change is False

    @pytest.mark.asyncio
    async def test_compare_threshold_exceeds(self) -> None:
        """Test is_significant_change when threshold is exceeded."""
        comparator = AccurateComparator(mismatch_threshold=5.0)
        img1 = create_test_image()
        img2 = create_test_image()

        mock_context = MagicMock()
        mock_page = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_page.route = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock(
            return_value={
                "totalPixels": 10000,
                "differentPixels": 501,
                "mismatchPercentage": 5.01,
                "diffBase64": "base64_string",
                "dimensionMismatch": False,
            }
        )
        mock_page.unroute = AsyncMock()
        mock_page.close = AsyncMock()

        result = await comparator.compare(mock_context, img1, img2)

        assert result.mismatch_percentage == 5.01
        assert result.is_significant_change is True

    @pytest.mark.asyncio
    async def test_compare_cleanup_on_success(self) -> None:
        """Test that resources are cleaned up after successful comparison."""
        comparator = AccurateComparator()
        img_b64 = create_test_image()

        mock_context = MagicMock()
        mock_page = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_page.route = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock(
            return_value={
                "totalPixels": 10000,
                "differentPixels": 0,
                "mismatchPercentage": 0.0,
                "diffBase64": "base64_string",
                "dimensionMismatch": False,
            }
        )
        mock_page.unroute = AsyncMock()
        mock_page.close = AsyncMock()

        await comparator.compare(mock_context, img_b64, img_b64)

        assert mock_page.unroute.call_count == 3
        mock_page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_compare_cleanup_on_exception(self) -> None:
        """Test that resources are cleaned up even if comparison fails."""
        comparator = AccurateComparator()
        img_b64 = create_test_image()

        mock_context = MagicMock()
        mock_page = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_page.route = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock(side_effect=Exception("Evaluation failed"))
        mock_page.unroute = AsyncMock()
        mock_page.close = AsyncMock()

        with pytest.raises(Exception, match="Evaluation failed"):
            await comparator.compare(mock_context, img_b64, img_b64)

        assert mock_page.unroute.call_count == 3
        mock_page.close.assert_called_once()

    def test_result_to_llm_message_similar(self) -> None:
        """Test to_llm_message for similar images."""
        result = AccurateComparisonResult(
            similarity=0.98,
            total_pixels=10000,
            different_pixels=200,
            mismatch_percentage=2.0,
            diff_image_b64="base64_string",
            dimension_mismatch=False,
            is_significant_change=False,
        )

        message = result.to_llm_message()

        assert "SIMILAR" in message
        assert "Similarity: 98.0%" in message
        assert "Mismatch: 2.00%" in message
        assert "200 of 10,000 pixels" in message
        assert "Canvas API" in message

    def test_result_to_llm_message_significant_change(self) -> None:
        """Test to_llm_message for significantly different images."""
        result = AccurateComparisonResult(
            similarity=0.20,
            total_pixels=10000,
            different_pixels=8000,
            mismatch_percentage=80.0,
            diff_image_b64="base64_diff_string",
            dimension_mismatch=False,
            is_significant_change=True,
        )

        message = result.to_llm_message()

        assert "SIGNIFICANT CHANGE" in message
        assert "Similarity: 20.0%" in message
        assert "Mismatch: 80.00%" in message
        assert "8,000 of 10,000 pixels" in message

    def test_result_to_llm_message_dimension_mismatch(self) -> None:
        """Test to_llm_message includes dimension mismatch warning."""
        result = AccurateComparisonResult(
            similarity=0.0,
            total_pixels=20000,
            different_pixels=20000,
            mismatch_percentage=100.0,
            diff_image_b64="base64_string",
            dimension_mismatch=True,
            is_significant_change=True,
        )

        message = result.to_llm_message()

        assert "dimension mismatch" in message
        assert "images have different sizes" in message

    def test_result_immutability(self) -> None:
        """Test that AccurateComparisonResult is immutable (frozen dataclass)."""
        result = AccurateComparisonResult(
            similarity=1.0,
            total_pixels=10000,
            different_pixels=0,
            mismatch_percentage=0.0,
            diff_image_b64="base64_string",
            dimension_mismatch=False,
            is_significant_change=False,
        )

        with pytest.raises(Exception):
            result.similarity = 0.5  # type: ignore[misc]

    def test_result_protocol_compliance(self) -> None:
        """Test that AccurateComparisonResult implements ComparisonResult protocol."""
        result = AccurateComparisonResult(
            similarity=1.0,
            total_pixels=10000,
            different_pixels=0,
            mismatch_percentage=0.0,
            diff_image_b64="base64_string",
            dimension_mismatch=False,
            is_significant_change=False,
        )

        assert hasattr(result, "similarity")
        assert hasattr(result, "is_significant_change")
        assert hasattr(result, "algorithm")
        assert hasattr(result, "to_llm_message")
        assert callable(result.to_llm_message)

    async def test_cleanup_handles_unroute_exception(self) -> None:
        """Test compare gracefully handles exceptions during unroute cleanup."""
        comparator = AccurateComparator()
        img = create_test_image()

        context = AsyncMock()
        diff_page = AsyncMock()
        context.new_page.return_value = diff_page

        diff_page.evaluate.return_value = {
            "totalPixels": 10000,
            "differentPixels": 0,
            "mismatchPercentage": 0.0,
            "diffBase64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "dimensionMismatch": False,
        }

        diff_page.unroute.side_effect = RuntimeError("Unroute failed")

        result = await comparator.compare(context, img, img)

        assert result.similarity == 1.0
        assert not result.is_significant_change
        assert diff_page.close.called

    async def test_cleanup_handles_close_exception(self) -> None:
        """Test compare gracefully handles exceptions during page close."""
        comparator = AccurateComparator()
        img = create_test_image()

        context = AsyncMock()
        diff_page = AsyncMock()
        context.new_page.return_value = diff_page

        diff_page.evaluate.return_value = {
            "totalPixels": 10000,
            "differentPixels": 0,
            "mismatchPercentage": 0.0,
            "diffBase64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "dimensionMismatch": False,
        }

        diff_page.close.side_effect = RuntimeError("Close failed")

        result = await comparator.compare(context, img, img)

        assert result.similarity == 1.0
        assert not result.is_significant_change
        assert diff_page.unroute.called

    async def test_cleanup_handles_both_exceptions(self) -> None:
        """Test compare gracefully handles exceptions during both unroute and close."""
        comparator = AccurateComparator()
        img = create_test_image()

        context = AsyncMock()
        diff_page = AsyncMock()
        context.new_page.return_value = diff_page

        diff_page.evaluate.return_value = {
            "totalPixels": 10000,
            "differentPixels": 0,
            "mismatchPercentage": 0.0,
            "diffBase64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "dimensionMismatch": False,
        }

        diff_page.unroute.side_effect = RuntimeError("Unroute failed")
        diff_page.close.side_effect = RuntimeError("Close failed")

        result = await comparator.compare(context, img, img)

        assert result.similarity == 1.0
        assert not result.is_significant_change

    async def test_route_handlers_invocation(self) -> None:
        """Test route handlers (_serve_blank, _serve_baseline, _serve_current) are invoked."""
        comparator = AccurateComparator()
        img = create_test_image()

        context = AsyncMock()
        diff_page = AsyncMock()
        context.new_page.return_value = diff_page

        handlers_invoked = []

        async def capture_and_invoke_handler(url: str, handler) -> None:
            """Capture route URL and invoke the handler to trigger line coverage."""
            handlers_invoked.append(url)
            mock_route = AsyncMock()
            await handler(mock_route)

        diff_page.route = capture_and_invoke_handler
        diff_page.evaluate.return_value = {
            "totalPixels": 10000,
            "differentPixels": 0,
            "mismatchPercentage": 0.0,
            "diffBase64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "dimensionMismatch": False,
        }

        result = await comparator.compare(context, img, img)

        assert result.similarity == 1.0
        assert len(handlers_invoked) == 3

    async def test_js_result_missing_required_keys(self) -> None:
        """Test that compare raises ValueError when JS result is missing required keys."""
        comparator = AccurateComparator()
        img = create_test_image()

        context = AsyncMock()
        diff_page = AsyncMock()
        context.new_page.return_value = diff_page

        diff_page.evaluate.return_value = {
            "totalPixels": 10000,
        }

        with pytest.raises(ValueError, match="missing required keys"):
            await comparator.compare(context, img, img)

    async def test_js_result_not_dict(self) -> None:
        """Test that compare raises TypeError when JS result is not a dict."""
        comparator = AccurateComparator()
        img = create_test_image()

        context = AsyncMock()
        diff_page = AsyncMock()
        context.new_page.return_value = diff_page

        diff_page.evaluate.return_value = "not a dict"

        with pytest.raises(TypeError, match="Expected dict from JS"):
            await comparator.compare(context, img, img)
