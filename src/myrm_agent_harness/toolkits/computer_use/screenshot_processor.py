"""Screenshot preprocessing pipeline.

Pre-resize screenshots to satisfy model vision encoder constraints, avoiding
server-side resize that causes coordinate drift (~14% on Retina displays).

Algorithm ported from Anthropic's reference implementation with multi-model support.

[INPUT]
- types::ImageConstraints, ScreenInfo (POS: shared type definitions)
- PIL.Image (POS: image processing)

[OUTPUT]
- ScreenshotProcessor: stateless processor with resize + encode pipeline
- target_image_size: binary-search algorithm for optimal resolution

[POS]
Stateless image processing pipeline. Called by ComputerSession on every screenshot.
"""

from __future__ import annotations

import base64
import io
import logging

from PIL import Image

from myrm_agent_harness.toolkits.computer_use.types import ImageConstraints, ScreenInfo

logger = logging.getLogger(__name__)


class ScreenshotTooSmall(ValueError):  # noqa: N818  intentional descriptive name
    """Screenshot is too small, likely a failed capture or missing permissions."""


def _n_tokens_for_px(px: int, px_per_token: int) -> int:
    """Ceiling division of pixel count by token tile size."""
    return (px - 1) // px_per_token + 1


def _n_tokens_for_img(w: int, h: int, px_per_token: int) -> int:
    return _n_tokens_for_px(w, px_per_token) * _n_tokens_for_px(h, px_per_token)


def target_image_size(
    width: int,
    height: int,
    constraints: ImageConstraints,
) -> tuple[int, int]:
    """Largest (w, h) preserving aspect ratio within vision encoder budget.

    Binary-search algorithm from Anthropic's reference implementation.
    Returns input unchanged if already within constraints.
    """
    ppt = constraints.px_per_token
    max_edge = constraints.max_edge_px
    max_tok = constraints.max_tokens

    if (
        width <= max_edge
        and height <= max_edge
        and _n_tokens_for_img(width, height, ppt) <= max_tok
    ):
        return width, height

    if height > width:
        w, h = target_image_size(height, width, constraints)
        return h, w

    aspect = width / height
    lo, hi = 1, width

    while lo + 1 < hi:
        mid_w = (lo + hi) // 2
        mid_h = max(round(mid_w / aspect), 1)
        if mid_w <= max_edge and _n_tokens_for_img(mid_w, mid_h, ppt) <= max_tok:
            lo = mid_w
        else:
            hi = mid_w

    return lo, max(round(lo / aspect), 1)


class ScreenshotProcessor:
    """Stateless screenshot preprocessing pipeline.

    1. Account for DPI scale (Retina 2x → actual pixel count)
    2. Binary-search optimal target resolution within model constraints
    3. LANCZOS downscale to target size
    4. JPEG 75% encode → base64 string

    Thread-safe: no mutable state.
    """

    def __init__(self, constraints: ImageConstraints | None = None) -> None:
        self._constraints = constraints or ImageConstraints()

    @property
    def constraints(self) -> ImageConstraints:
        return self._constraints

    def process(
        self,
        png_bytes: bytes,
        screen_info: ScreenInfo,
    ) -> tuple[str, tuple[int, int]]:
        """Process raw screenshot bytes into base64 JPEG.

        Args:
            png_bytes: Raw PNG screenshot bytes
            screen_info: Screen dimensions and DPI scale

        Returns:
            (base64_jpeg_string, (sent_width, sent_height))

        Raises:
            ScreenshotTooSmall: if encoded result is suspiciously small
        """
        img = Image.open(io.BytesIO(png_bytes))

        tw, th = target_image_size(img.width, img.height, self._constraints)

        if (tw, th) != (img.width, img.height):
            img = img.resize((tw, th), Image.Resampling.LANCZOS)

        if img.mode != "RGB":
            img = img.convert("RGB")

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=self._constraints.jpeg_quality)
        data = buf.getvalue()

        if len(data) < self._constraints.min_screenshot_bytes:
            raise ScreenshotTooSmall(
                f"Screenshot is {len(data)} bytes (< {self._constraints.min_screenshot_bytes}). "
                "This usually means Screen Recording permission is missing or the capture failed."
            )

        return base64.standard_b64encode(data).decode("ascii"), (tw, th)

    def crop_and_process(
        self,
        png_bytes: bytes,
        region: tuple[int, int, int, int],
        screen_info: ScreenInfo,
    ) -> tuple[str, tuple[int, int]]:
        """Crop a region from screenshot and process it (for zoom capability).

        Args:
            png_bytes: Raw PNG screenshot bytes
            region: (left, top, right, bottom) in physical pixel coordinates
            screen_info: Screen dimensions and DPI

        Returns:
            (base64_jpeg_string, (sent_width, sent_height))
        """
        img = Image.open(io.BytesIO(png_bytes))
        cropped = img.crop(region)

        cropped_bytes = io.BytesIO()
        cropped.save(cropped_bytes, format="PNG")
        return self.process(cropped_bytes.getvalue(), screen_info)
