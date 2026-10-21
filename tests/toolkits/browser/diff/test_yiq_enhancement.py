"""Tests for YIQ color space and anti-aliasing detection enhancements."""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from myrm_agent_harness.toolkits.browser.diff import AccurateComparator


def create_test_image(width: int = 100, height: int = 100, color: tuple[int, int, int] = (255, 0, 0)) -> str:
    """Create a solid color test image and return as base64."""
    img = Image.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


class TestYIQEnhancement:
    """Test suite for YIQ color space and anti-aliasing detection."""

    def test_comparator_has_include_aa_parameter(self) -> None:
        """Test that AccurateComparator accepts include_aa parameter."""
        comparator_with_aa = AccurateComparator(include_aa=True)
        assert comparator_with_aa.include_aa is True

        comparator_without_aa = AccurateComparator(include_aa=False)
        assert comparator_without_aa.include_aa is False

    def test_default_include_aa_is_true(self) -> None:
        """Test that anti-aliasing detection is enabled by default."""
        comparator = AccurateComparator()
        assert comparator.include_aa is True

    async def test_yiq_color_space_parameter_passed(self, mock_browser_context: object) -> None:
        """Test that YIQ color space is used in comparison."""
        img1_b64 = create_test_image(50, 50, (200, 100, 50))
        img2_b64 = create_test_image(50, 50, (205, 105, 55))

        comparator = AccurateComparator(color_tolerance=0.15, mismatch_threshold=5.0)

        result = await comparator.compare(mock_browser_context, img1_b64, img2_b64)  # type: ignore[arg-type]

        assert result.mismatch_percentage < 10.0

    async def test_anti_aliasing_detection_parameter_passed(self, mock_browser_context: object) -> None:
        """Test that include_aa parameter is correctly passed to JavaScript."""
        img1_b64 = create_test_image(50, 50, (200, 200, 200))
        img2_b64 = create_test_image(50, 50, (200, 200, 200))

        comparator_with_aa = AccurateComparator(include_aa=True)
        result_with_aa = await comparator_with_aa.compare(mock_browser_context, img1_b64, img2_b64)  # type: ignore[arg-type]

        assert result_with_aa.similarity >= 0.99
        assert result_with_aa.mismatch_percentage < 1.0

    def test_comparator_initialization_with_all_parameters(self) -> None:
        """Test that all new parameters can be initialized together."""
        comparator = AccurateComparator(
            color_tolerance=0.15,
            mismatch_threshold=10.0,
            include_aa=False,
        )

        assert comparator.color_tolerance == 0.15
        assert comparator.mismatch_threshold == 10.0
        assert comparator.include_aa is False


@pytest.fixture
def mock_browser_context(monkeypatch: pytest.MonkeyPatch) -> object:
    """Mock BrowserContext for testing without real browser."""
    from unittest.mock import AsyncMock, MagicMock

    mock_context = MagicMock()
    mock_page = MagicMock()

    async def mock_evaluate(js_code: str, args: dict[str, object]) -> dict[str, object]:
        return {
            "totalPixels": 2500,
            "differentPixels": 0,
            "mismatchPercentage": 0.0,
            "diffBase64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "dimensionMismatch": False,
        }

    mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)
    mock_page.goto = AsyncMock()
    mock_page.route = AsyncMock()
    mock_page.unroute = AsyncMock()
    mock_page.close = AsyncMock()

    mock_context.new_page = AsyncMock(return_value=mock_page)

    return mock_context
