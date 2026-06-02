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
    """统一 Screenshot对比管理器

    职责:
    1. provides统一 对比Interface
    2. SupportAutoStrategy选择
    3. ParameterValidate and default value管理

     not 涉 and :ScreenshotExtract、Page操作 etc.。
    """

    def __init__(self, context: BrowserContext):
        """Initialize ScreenshotComparator

        Args:
            context: Patchright BrowserContext Instance
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
        """对比两张Screenshot

        Args:
            baseline: Base64 Encoding 基准Screenshot
            current: Base64 Encoding CurrentScreenshot
            strategy: 对比Strategy
                - 'auto': Auto选择( based on ImageSize,<800x600 用 accurate,Otherwise用 fast)
                - 'fast': dHash fast检测(~2ms),Return相似度
                - 'accurate': Canvas API 像素级对比(~100ms),Return diff 图
            similarity_threshold: Fast Strategy 相似度阈Value (0.0-1.0, Default 0.9)
            color_tolerance: Accurate Strategy 颜色容忍度 (0.0-1.0, Default 0.1)
            mismatch_threshold: Accurate Strategy  not Match阈Value (0-100, Default 5.0)
            include_aa: Accurate StrategyWhether启用抗锯齿检测 (Default True)

        Returns:
            FastComparisonResult: strategy='fast'  or  auto 选择 fast 时
            AccurateComparisonResult: strategy='accurate'  or  auto 选择 accurate 时

        Raises:
            ValueError: If strategy  not 是 'fast', 'accurate',  or  'auto'
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
        """Auto选择对比Strategy

        Strategy:
        - Image < 800x600 (480K 像素) → 'accurate' (exact对比成本可接受)
        - Image >= 800x600 → 'fast' (大图用fast检测)

        Args:
            screenshot_b64: Base64 Encoding Screenshot

        Returns:
            'fast'  or  'accurate'
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
