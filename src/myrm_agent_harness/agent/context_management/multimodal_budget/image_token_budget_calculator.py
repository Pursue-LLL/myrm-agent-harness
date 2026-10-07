"""Calculates token expenditure for file images based on tile decomposition geometry.

Implements industry-standard vision token models (GPT-4o/Codex/Claude style)
mapping pixel resolutions and aspect ratios to discrete 512x512 tile costs.
"""

from __future__ import annotations

import math

from .multimodal_budget_types import (
    ImageDetailMode,
    ImageResolution,
)


class ImageTokenBudgetCalculator:
    """Computes exact token requirements for image resolutions using tile geometry."""

    BASE_TOKENS = 85
    PER_TILE_TOKENS = 170
    TILE_SIZE = 512
    MAX_LONG_EDGE = 2048
    TARGET_SHORT_EDGE = 768
    PLACEHOLDER_TOKENS = 20

    def calculate_image_tokens(
        self,
        resolution: ImageResolution,
        detail_mode: ImageDetailMode = ImageDetailMode.AUTO,
    ) -> tuple[int, int]:
        """Compute estimated token usage and tile count for an image resolution.

        Returns (token_count, tile_count).
        """
        # Low detail mode always consumes a fixed base token budget
        if detail_mode == ImageDetailMode.LOW:
            return self.BASE_TOKENS, 0

        # Auto or High detail mode: compute scale and tile count
        scaled_w, scaled_h = self._scale_to_vision_bounds(resolution.width, resolution.height)
        tiles_x = math.ceil(scaled_w / self.TILE_SIZE)
        tiles_y = math.ceil(scaled_h / self.TILE_SIZE)
        tile_count = max(1, tiles_x * tiles_y)

        total_tokens = tile_count * self.PER_TILE_TOKENS + self.BASE_TOKENS
        return total_tokens, tile_count

    def _scale_to_vision_bounds(self, width: int, height: int) -> tuple[int, int]:
        """Scale dimensions so long edge <= 2048 and short edge is scaled to 768."""
        w, h = float(max(1, width)), float(max(1, height))

        # 1. Scale down long edge to fit within MAX_LONG_EDGE
        max_dim = max(w, h)
        if max_dim > self.MAX_LONG_EDGE:
            ratio = self.MAX_LONG_EDGE / max_dim
            w *= ratio
            h *= ratio

        # 2. Scale shortest edge to TARGET_SHORT_EDGE if larger
        min_dim = min(w, h)
        if min_dim > self.TARGET_SHORT_EDGE:
            ratio = self.TARGET_SHORT_EDGE / min_dim
            w *= ratio
            h *= ratio

        return int(round(w)), int(round(h))
