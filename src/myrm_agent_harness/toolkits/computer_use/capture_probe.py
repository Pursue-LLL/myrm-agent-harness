"""Capture readiness helper for desktop permission probing.

[INPUT]
- PIL.Image (optional): decode PNG samples for luminance checks

[OUTPUT]
- png_bytes_look_capturable: bool gate for usable non-black/white frames

[POS]
Shared functional capture probe used by platform check_permissions(probe_capture=True).
"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

_MIN_PNG_BYTES = 64


def png_bytes_look_capturable(data: bytes, *, min_bytes: int = _MIN_PNG_BYTES) -> bool:
    """Return True when *data* looks like a usable screen capture.

    Uses a center 3x3 sample grid. Rejects frames whose samples are all near
    pure black or all near pure white (stale grant / locked screen).
    """
    if len(data) < min_bytes:
        return False
    try:
        from PIL import Image
    except ImportError:
        return True

    try:
        img = Image.open(io.BytesIO(data))
        rgb = img.convert("RGB")
        width, height = rgb.size
        if width < 8 or height < 8:
            return False
        luminances: list[float] = []
        for yi in (1, 2, 3):
            for xi in (1, 2, 3):
                x = max(0, min(width - 1, (width * xi) // 4))
                y = max(0, min(height - 1, (height * yi) // 4))
                pixel = rgb.getpixel((x, y))
                if not isinstance(pixel, tuple) or len(pixel) < 3:
                    return False
                r, g, b = int(pixel[0]), int(pixel[1]), int(pixel[2])
                luminances.append(0.299 * r + 0.587 * g + 0.114 * b)
        mean_l = sum(luminances) / len(luminances)
        spread = max(luminances) - min(luminances)
        if mean_l <= 2.0 or mean_l >= 253.0:
            if spread <= 2.0:
                return False
        return True
    except Exception as exc:
        logger.debug("Capture probe PNG decode failed: %s", exc)
        return False
