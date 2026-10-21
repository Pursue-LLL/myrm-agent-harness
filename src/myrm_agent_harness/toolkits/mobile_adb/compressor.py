"""Screenshot compression for wireless Android screencap streaming.

[INPUT]
- raw_png_bytes: bytes, max_dimension: int, quality: int, output_format: 'WEBP' | 'JPEG'

[OUTPUT]
- compress_screencap_bytes -> bytes (downscaled + re-encoded image bytes)

[POS]
Bandwidth/latency optimization for mobile screencap payloads. Wireless ADB transfers are
the dominant cost of a mobile snapshot, so every screenshot is re-encoded before it
enters LLM context. Falls back to the raw PNG when Pillow is unavailable or encoding fails.
"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)


def compress_screencap_bytes(
    raw_png_bytes: bytes,
    max_dimension: int = 1280,
    quality: int = 80,
    output_format: str = "WEBP",
) -> bytes:
    """Downscale and re-encode raw screencap PNG bytes into WebP/JPEG."""
    if not raw_png_bytes or len(raw_png_bytes) < 64:
        return raw_png_bytes

    try:
        from PIL import Image

        image = Image.open(io.BytesIO(raw_png_bytes))

        width, height = image.size
        if max(width, height) > max_dimension:
            if width > height:
                new_width = max_dimension
                new_height = int(height * (max_dimension / width))
            else:
                new_height = max_dimension
                new_width = int(width * (max_dimension / height))
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        if output_format.upper() == "JPEG" and image.mode in ("RGBA", "P"):
            image = image.convert("RGB")

        out_buffer = io.BytesIO()
        image.save(out_buffer, format=output_format.upper(), quality=quality, optimize=True)
        compressed = out_buffer.getvalue()
        logger.debug(
            "Compressed screencap from %d KB to %d KB (%s)",
            len(raw_png_bytes) // 1024,
            len(compressed) // 1024,
            output_format,
        )
        return compressed
    except ImportError:
        logger.warning("Pillow not installed; returning uncompressed PNG bytes.")
        return raw_png_bytes
    except Exception as exc:
        logger.warning("Failed to compress screenshot (%s); falling back to raw PNG.", exc)
        return raw_png_bytes
