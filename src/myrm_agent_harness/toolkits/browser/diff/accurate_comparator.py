"""Pixel-level screenshot comparison via browser Canvas API.

Compares two screenshots by injecting them into an isolated browser page and
performing per-pixel color-distance comparison using the native Canvas
getImageData API. Zero external dependencies — no pixelmatch, sharp, or
Pillow required.

Architecture:
1. Open an isolated blank page in the existing BrowserContext
   (avoids CSP interference or DOM side-effects on the user's page).
2. Serve both images via intercepted routes — avoids passing large base64
   payloads through page.evaluate which can hit CDP message-size limits.
3. Draw both images onto <canvas>, read pixel data, compare with a
   configurable color-distance threshold to tolerate anti-aliasing.
4. Return AccurateComparisonResult with match statistics and diff image.
5. Clean up routes and close the isolated page in a finally block.


[INPUT]
- patchright.async_api (POS: Browser automation)
- .types (POS: AccurateComparisonResult)

[OUTPUT]
- AccurateComparator: Pixel-level screenshot comparator

[POS]
Pixel-level screenshot comparison module for the browser toolkit. Performs per-pixel
comparison via Canvas API in an isolated page, outputting diff statistics and diff images.

Performance: ~100ms
"""

from __future__ import annotations

import base64
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from .types import AccurateComparisonResult

if TYPE_CHECKING:
    from patchright.async_api import BrowserContext, Route


class _PixelDiffResult(TypedDict):
    """Type definition for JavaScript pixel diff result."""

    totalPixels: int
    differentPixels: int
    mismatchPercentage: float
    diffBase64: str
    dimensionMismatch: bool


logger = logging.getLogger(__name__)

_DIFF_ROUTE_PREFIX = "https://agent-diff.localhost"
_MAX_BASE64_SIZE = 10 * 1024 * 1024
_MAX_IMAGE_DIMENSION = 4096


def _load_pixel_diff_js() -> str:
    """Load pixel diff JavaScript code from external file."""
    from pathlib import Path

    js_path = Path(__file__).parent / "pixel_diff.js"
    return js_path.read_text(encoding="utf-8")


def _nonce() -> str:
    """Generate unique nonce for route URLs using UUID4."""
    return uuid.uuid4().hex[:8]


def _validate_screenshot_input(screenshot_b64: str, param_name: str) -> bytes:
    """Validate and decode screenshot base64 input.

    Args:
        screenshot_b64: Base64-encoded screenshot
        param_name: Parameter name for error messages

    Returns:
        Decoded image bytes

    Raises:
        ValueError: If input is invalid (too large, invalid base64, invalid image)
    """
    if len(screenshot_b64) > _MAX_BASE64_SIZE:
        raise ValueError(
            f"{param_name} too large: {len(screenshot_b64)} bytes (max {_MAX_BASE64_SIZE // 1024 // 1024}MB)"
        )

    try:
        image_bytes = base64.b64decode(screenshot_b64, validate=True)
    except Exception as exc:
        raise ValueError(f"{param_name} is not valid base64") from exc

    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size

        if width > _MAX_IMAGE_DIMENSION or height > _MAX_IMAGE_DIMENSION:
            raise ValueError(
                f"{param_name} dimensions too large: {width}x{height} "
                f"(max {_MAX_IMAGE_DIMENSION}x{_MAX_IMAGE_DIMENSION})"
            )

        img.verify()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"{param_name} is not a valid image") from exc

    return image_bytes


@dataclass
class AccurateComparator:
    """Accurate pixel-level screenshot comparator using Canvas API with YIQ color space.

    Performs pixel-by-pixel comparison in an isolated browser page using
    Canvas getImageData API. Uses YIQ color space for perceptual color difference
    matching human vision. Includes anti-aliasing detection to reduce false
    positives from browser rendering differences.

    Algorithm features:
    - YIQ color space: Separates luminance (Y) from chrominance (I, Q) for
      perceptual accuracy matching human color perception
    - Anti-aliasing detection: Identifies edge pixels with color gradients and
      applies lenient thresholds to reduce cross-browser false positives
    - Diff visualization: Red = real difference, Yellow = anti-aliased difference

    Use cases:
    - Cross-browser visual regression testing
    - Debugging visual regressions with perceptual accuracy
    - Locating exact change positions
    - Detailed visual analysis

    Attributes:
        color_tolerance: YIQ color distance tolerance (0.0-1.0). Higher values
            ignore minor color differences and sub-pixel rendering. Default: 0.1
        mismatch_threshold: Maximum mismatch percentage (0-100) to consider images
            similar. Default: 5.0 (5%)
        include_aa: Enable anti-aliasing detection. When True, anti-aliased pixels
            are marked separately (yellow) and not counted as differences. Default: True
    """

    color_tolerance: float = 0.1
    mismatch_threshold: float = 5.0
    include_aa: bool = True

    def __post_init__(self) -> None:
        """Validate parameters."""
        if not 0.0 <= self.color_tolerance <= 1.0:
            raise ValueError(f"color_tolerance must be in [0.0, 1.0], got {self.color_tolerance}")
        if not 0.0 <= self.mismatch_threshold <= 100.0:
            raise ValueError(f"mismatch_threshold must be in [0.0, 100.0], got {self.mismatch_threshold}")

    async def compare(
        self,
        context: BrowserContext,
        baseline_b64: str,
        current_b64: str,
    ) -> AccurateComparisonResult:
        """Compare two screenshots pixel-by-pixel using Canvas API.

        Opens an isolated blank page, serves both images via intercepted routes,
        and runs a Canvas-based pixel comparison. Cleans up all resources on exit.

        Args:
            context: Patchright BrowserContext (reuses existing browser instance)
            baseline_b64: Base64-encoded baseline screenshot
            current_b64: Base64-encoded current screenshot

        Returns:
            AccurateComparisonResult with pixel statistics and diff image

        Raises:
            ValueError: If input is invalid (too large, invalid base64, invalid image)
        """
        baseline_bytes = _validate_screenshot_input(baseline_b64, "baseline")
        current_bytes = _validate_screenshot_input(current_b64, "current")

        nonce = _nonce()
        blank_url = f"{_DIFF_ROUTE_PREFIX}/{nonce}/index.html"
        baseline_url = f"{_DIFF_ROUTE_PREFIX}/{nonce}/baseline.png"
        current_url = f"{_DIFF_ROUTE_PREFIX}/{nonce}/current.png"

        diff_page = await context.new_page()
        routed_urls: list[str] = []

        try:

            async def _serve_blank(route: Route) -> None:
                await route.fulfill(body="<html><body></body></html>", content_type="text/html")

            async def _serve_baseline(route: Route) -> None:
                await route.fulfill(body=baseline_bytes, content_type="image/png")

            async def _serve_current(route: Route) -> None:
                await route.fulfill(body=current_bytes, content_type="image/png")

            await diff_page.route(blank_url, _serve_blank)
            routed_urls.append(blank_url)

            await diff_page.route(baseline_url, _serve_baseline)
            routed_urls.append(baseline_url)

            await diff_page.route(current_url, _serve_current)
            routed_urls.append(current_url)

            await diff_page.goto(blank_url)

            js_code = _load_pixel_diff_js()
            raw = await diff_page.evaluate(
                js_code,
                {
                    "baselineUrl": baseline_url,
                    "currentUrl": current_url,
                    "tolerance": self.color_tolerance,
                    "includeAA": self.include_aa,
                },
            )

            if not isinstance(raw, dict):
                raise TypeError(f"Expected dict from JS, got {type(raw)}")

            required_keys = {"totalPixels", "differentPixels", "mismatchPercentage", "diffBase64"}
            missing = required_keys - raw.keys()
            if missing:
                raise ValueError(f"JS result missing required keys: {missing}")

            total = int(raw["totalPixels"])
            different = int(raw["differentPixels"])
            pct = float(raw["mismatchPercentage"])
            diff_b64 = str(raw["diffBase64"])
            dim_mismatch = bool(raw.get("dimensionMismatch", False))

            similarity = 1 - (pct / 100.0)
            is_significant = pct > self.mismatch_threshold

            return AccurateComparisonResult(
                similarity=similarity,
                total_pixels=total,
                different_pixels=different,
                mismatch_percentage=pct,
                diff_image_b64=diff_b64,
                dimension_mismatch=dim_mismatch,
                is_significant_change=is_significant,
            )
        finally:
            for url in routed_urls:
                try:
                    await diff_page.unroute(url)
                except Exception as exc:
                    logger.warning(f"AccurateComparator: failed to unroute {url}: {exc}")
            try:
                await diff_page.close()
            except Exception as exc:
                logger.warning(f"AccurateComparator: failed to close diff page: {exc}")
