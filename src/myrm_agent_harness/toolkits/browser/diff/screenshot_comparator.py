"""Screenshot comparison manager — unified interface for fast and accurate comparison.


[INPUT]
- .fast_comparator (POS: dHash fast comparison)
- .accurate_comparator (POS: Canvas API accurate comparison)
- .types (POS: ComparisonResult)

[OUTPUT]
- ScreenshotComparator: unified screenshot comparison manager

[POS]
Screenshot comparison manager. Provides a unified interface for fast and accurate comparison, with automatic strategy selection.
Single responsibility: only handles screenshot comparison logic; does not handle screenshot capture, page operations, etc.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import TYPE_CHECKING, Literal

from .accurate_comparator import AccurateComparator
from .fast_comparator import FastComparator
from .types import AccurateComparisonResult, FastComparisonResult

if TYPE_CHECKING:
    from patchright.async_api import BrowserContext

logger = logging.getLogger(__name__)

_AUTO_STRATEGY_THRESHOLD = 800 * 600


class ScreenshotComparator:
    """Unified screenshot comparison manager.

    Responsibilities:
    1. Unified comparison interface (fast / accurate / auto)
    2. Automatic strategy selection based on image dimensions
    3. Parameter validation and defaults

    Does NOT handle screenshot capture or page operations.
    """

    def __init__(self, context: BrowserContext):
        """Initialize ScreenshotComparator.

        Args:
            context: Patchright BrowserContext instance for accurate comparison.
        """
        self._context = context

    async def compare(
        self,
        baseline: str,
        current: str,
        strategy: Literal["fast", "accurate", "auto"] = "auto",
        similarity_threshold: float = 0.9,
        color_tolerance: float = 0.1,
        mismatch_threshold: float = 5.0,
        include_aa: bool = True,
    ) -> FastComparisonResult | AccurateComparisonResult:
        """Compare two screenshots.

        Args:
            baseline: Base64-encoded baseline screenshot.
            current: Base64-encoded current screenshot.
            strategy: Comparison strategy.
                - 'auto': auto-select based on image size (<800x600 → accurate, else → fast)
                - 'fast': dHash perceptual hash (~2ms), returns similarity score
                - 'accurate': Canvas API pixel-level diff (~100ms), returns diff image
            similarity_threshold: Similarity threshold for fast strategy (0.0-1.0, default 0.9).
            color_tolerance: Color tolerance for accurate strategy (0.0-1.0, default 0.1).
            mismatch_threshold: Mismatch threshold for accurate strategy (0-100, default 5.0).
            include_aa: Enable anti-aliasing detection for accurate strategy (default True).

        Returns:
            FastComparisonResult when strategy is 'fast' or auto selects fast.
            AccurateComparisonResult when strategy is 'accurate' or auto selects accurate.

        Raises:
            ValueError: If strategy is not 'fast', 'accurate', or 'auto'.
        """
        actual_strategy = strategy

        if strategy == "auto":
            actual_strategy = self._select_strategy(current)

        if actual_strategy == "fast":
            comparator = FastComparator(similarity_threshold=similarity_threshold)
            return comparator.compare(baseline, current)
        elif actual_strategy == "accurate":
            comparator = AccurateComparator(
                color_tolerance=color_tolerance,
                mismatch_threshold=mismatch_threshold,
                include_aa=include_aa,
            )
            return await comparator.compare(self._context, baseline, current)
        else:
            raise ValueError(f"Invalid strategy: {strategy}. Must be 'fast', 'accurate', or 'auto'.")

    def _select_strategy(self, screenshot_b64: str) -> Literal["fast", "accurate"]:
        """Auto-select comparison strategy based on image dimensions.

        Strategy:
        - Image < 800x600 (480K pixels) → 'accurate' (pixel-level cost is acceptable)
        - Image >= 800x600 → 'fast' (perceptual hash for large images)

        Args:
            screenshot_b64: Base64-encoded screenshot.

        Returns:
            'fast' or 'accurate'.
        """
        try:
            from PIL import Image

            img_bytes = base64.b64decode(screenshot_b64)
            img = Image.open(io.BytesIO(img_bytes))
            width, height = img.size
            total_pixels = width * height

            strategy: Literal["fast", "accurate"] = "accurate" if total_pixels < _AUTO_STRATEGY_THRESHOLD else "fast"

            logger.info(
                f"ScreenshotComparator: auto-selected '{strategy}' strategy "
                f"for {width}x{height} image ({total_pixels:,} pixels)"
            )
            return strategy
        except Exception as exc:
            logger.warning(f"ScreenshotComparator: failed to detect image size, defaulting to 'fast': {exc}")
            return "fast"
