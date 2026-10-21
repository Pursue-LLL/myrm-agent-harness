"""Coordinate normalization engine for cross-display DPI alignment.

Eradicates the anti-pattern of having language models compute coordinate arithmetic
in prompts. Normalizes percentage, Retina logical points, and physical pixels automatically.

[INPUT]
- __future__
- code_over_prompt_types

[OUTPUT]
- CoordinateNormalizer

[POS]
Coordinate normalization engine for cross-display DPI alignment.
"""

from __future__ import annotations

from .code_over_prompt_types import (
    CoordinateFormat,
    DisplayBounds,
    NormalizedPoint,
)


class CoordinateNormalizer:
    """Converts multi-format input coordinates into bounded physical device pixels."""

    def __init__(self, display: DisplayBounds) -> None:
        self.display = display

    def normalize(
        self,
        raw_x: float,
        raw_y: float,
        forced_format: CoordinateFormat = CoordinateFormat.AUTO_INFERRED,
    ) -> NormalizedPoint:
        """Resolve arbitrary input coordinates into validated physical pixel coordinates."""
        fmt = forced_format
        if fmt == CoordinateFormat.AUTO_INFERRED:
            fmt = self._infer_format(raw_x, raw_y)

        if fmt == CoordinateFormat.PERCENTAGE:
            calc_x = int(raw_x * self.display.width)
            calc_y = int(raw_y * self.display.height)
        elif fmt == CoordinateFormat.RETINA_SCALED:
            calc_x = int(raw_x * self.display.scale_factor)
            calc_y = int(raw_y * self.display.scale_factor)
        else:  # CoordinateFormat.PIXEL
            calc_x = int(raw_x)
            calc_y = int(raw_y)

        # Clamp coordinates to ensure they remain inside valid display boundaries
        clamped_x = max(0, min(calc_x, self.display.width - 1))
        clamped_y = max(0, min(calc_y, self.display.height - 1))

        return NormalizedPoint(
            x=clamped_x,
            y=clamped_y,
            raw_x=raw_x,
            raw_y=raw_y,
            format_detected=fmt,
        )

    def _infer_format(self, x: float, y: float) -> CoordinateFormat:
        """Infer coordinate format based on value range and float representation."""
        # Floating point ratios between 0.0 and 1.0 (exclusive of full screen edge boundary values > 1)
        if isinstance(x, float) and isinstance(y, float) and 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
            return CoordinateFormat.PERCENTAGE

        # Logical points are typically scaled down by the scale factor
        logical_max_w = self.display.width / self.display.scale_factor
        logical_max_h = self.display.height / self.display.scale_factor
        if x <= logical_max_w and y <= logical_max_h and self.display.scale_factor > 1.0:
            return CoordinateFormat.RETINA_SCALED

        return CoordinateFormat.PIXEL
