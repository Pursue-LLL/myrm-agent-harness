"""Image compression utility for mobile screenshot streaming over wireless networks.

[INPUT]
- png_bytes: bytes, max_width: int, quality: int, format: str ('WEBP' | 'JPEG')

[OUTPUT]
- compress_screencap_bytes -> bytes (compressed image bytes)

[POS]
Bandwidth and latency optimization pipeline for Mobile Computer Use.
"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)


def compress_screencap_bytes(
    png_bytes: bytes,
    max_dimension: int = 1280,
    quality: int = 80,
    output_format: str = "WEBP",
) -> bytes:
    """Compress raw PNG bytes into lightweight WebP or JPEG bytes with downscaling."""
    if not png_bytes or len(png_bytes) < 64:
        return png_bytes

    try:
        from PIL import Image

        image = Image.open(io.BytesIO(png_bytes))

        # Calculate proportional downscaled dimensions
        w, h = image.size
        if max(w, h) > max_dimension:
            if w > h:
                new_w = max_dimension
                new_h = int(h * (max_dimension / w))
            else:
                new_h = max_dimension
                new_w = int(w * (max_dimension / h))
            image = image.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # Convert to RGB if RGBA and saving as JPEG
        if output_format.upper() == "JPEG" and image.mode in ("RGBA", "P"):
            image = image.convert("RGB")

        out_buffer = io.BytesIO()
        image.save(out_buffer, format=output_format.upper(), quality=quality, optimize=True)
        compressed = out_buffer.getvalue()
        logger.debug(
            "Compressed screencap from %d KB to %d KB (%s)",
            len(png_bytes) // 1024,
            len(compressed) // 1024,
            output_format,
        )
        return compressed
    except ImportError:
        logger.warning("Pillow not installed; returning uncompressed PNG bytes.")
        return png_bytes
    except Exception as exc:
        logger.warning("Failed to compress screenshot (%s); falling back to raw PNG.", exc)
        return png_bytes
