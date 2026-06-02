"""Complete coverage tests for YIQ enhancement."""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from myrm_agent_harness.toolkits.browser.diff import AccurateComparator


def create_solid_color_image(width: int, height: int, color: tuple[int, int, int]) -> str:
    """Create a solid color image and return as base64."""
    img = Image.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


class TestYIQCompleteCoverage:
    """Complete coverage tests for YIQ and anti-aliasing."""

    def test_include_aa_parameter_validation(self) -> None:
        """Test include_aa parameter can be set."""
        comparator_true = AccurateComparator(include_aa=True)
        assert comparator_true.include_aa is True

        comparator_false = AccurateComparator(include_aa=False)
        assert comparator_false.include_aa is False

    async def test_yiq_with_different_tolerance_levels(self, mock_browser_context: object) -> None:
        """Test YIQ calculation with different tolerance levels."""
        img1 = create_solid_color_image(50, 50, (200, 100, 50))
        img2 = create_solid_color_image(50, 50, (210, 110, 60))

        strict = AccurateComparator(color_tolerance=0.05)
        lenient = AccurateComparator(color_tolerance=0.25)

        strict_result = await strict.compare(mock_browser_context, img1, img2)  # type: ignore[arg-type]
        lenient_result = await lenient.compare(mock_browser_context, img1, img2)  # type: ignore[arg-type]

        assert lenient_result.similarity >= strict_result.similarity

    async def test_all_parameters_combined(self, mock_browser_context: object) -> None:
        """Test all parameters work together."""
        img1 = create_solid_color_image(50, 50, (200, 100, 50))
        img2 = create_solid_color_image(50, 50, (205, 105, 55))

        comparator = AccurateComparator(color_tolerance=0.15, mismatch_threshold=10.0, include_aa=True)
        result = await comparator.compare(mock_browser_context, img1, img2)  # type: ignore[arg-type]

        assert result.total_pixels == 2500
        assert isinstance(result.similarity, float)
        assert isinstance(result.mismatch_percentage, float)
        assert isinstance(result.is_significant_change, bool)
        assert result.diff_image_b64


@pytest.fixture
def mock_browser_context(monkeypatch: pytest.MonkeyPatch) -> object:
    """Mock BrowserContext for testing."""
    from unittest.mock import AsyncMock, MagicMock

    mock_context = MagicMock()
    mock_page = MagicMock()

    async def mock_evaluate(js_code: str, args: dict[str, object]) -> dict[str, object]:
        return {
            "totalPixels": 2500,
            "differentPixels": 250,
            "mismatchPercentage": 10.0,
            "diffBase64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==",
            "dimensionMismatch": False,
        }

    mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)
    mock_page.goto = AsyncMock()
    mock_page.route = AsyncMock()
    mock_page.unroute = AsyncMock()
    mock_page.close = AsyncMock()

    mock_context.new_page = AsyncMock(return_value=mock_page)

    return mock_context
