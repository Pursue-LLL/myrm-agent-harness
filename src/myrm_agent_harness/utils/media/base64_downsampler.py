"""Stateless downsampler and metadata probe for base64 data URL images.

[INPUT]
- utils.image_utils::is_base64_data_url (POS: Base64 data URL validation)
- utils.logger_utils::get_agent_logger (POS: Agent logger)

[OUTPUT]
- downsample_base64_image: Downsamples base64 images to compact WebP format.
- probe_base64_image_meta: Extracts dimensions and format from base64 data URL.

[POS]
Pure image utility module providing stateless downsampling and header probing for base64
payloads without mutating message histories or depending on agent/session state.
"""

from __future__ import annotations

import base64
import io
from typing import Final

from PIL import Image

from myrm_agent_harness.utils.image_utils import is_base64_data_url
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

DEFAULT_DOWNSAMPLE_MAX_DIM: Final[int] = 512
DEFAULT_DOWNSAMPLE_QUALITY: Final[float] = 0.65


def downsample_base64_image(
    data_url: str,
    max_dim: int = DEFAULT_DOWNSAMPLE_MAX_DIM,
    quality: float = DEFAULT_DOWNSAMPLE_QUALITY,
) -> str | None:
    """Downsample a base64 data URL image to compact WebP format.

    Preserves aspect ratio, handles RGBA/palette modes gracefully, and falls
    back to the original data URL if compression yields no size savings.
    """
    if not is_base64_data_url(data_url):
        return None

    try:
        _header, b64_str = data_url.split(";base64,", 1)
        raw_bytes = base64.b64decode(b64_str)

        with Image.open(io.BytesIO(raw_bytes)) as img:
            # Preserve aspect ratio while resizing
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

            # Convert to RGB if palette or non-standard mode lacking WebP support
            rgb_img: Image.Image = img
            if img.mode in ("RGBA", "LA", "P"):
                pass  # WebP supports RGBA directly
            elif img.mode != "RGB":
                rgb_img = img.convert("RGB")

            out_buf = io.BytesIO()
            rgb_img.save(out_buf, format="WEBP", quality=int(quality * 100), method=4)
            compressed_bytes = out_buf.getvalue()

            if len(compressed_bytes) >= len(raw_bytes):
                return data_url

            new_b64 = base64.b64encode(compressed_bytes).decode("ascii")
            return f"data:image/webp;base64,{new_b64}"
    except Exception as exc:
        logger.debug("[Base64Downsampler] Downsampling failed: %s", exc)
        return None


def probe_base64_image_meta(data_url: str) -> tuple[int, int, str] | None:
    """Extract intrinsic (width, height, format) from a base64 data URL without full pixel decode."""
    if not is_base64_data_url(data_url):
        return None

    try:
        _header, b64_str = data_url.split(";base64,", 1)
        raw_bytes = base64.b64decode(b64_str)
        with Image.open(io.BytesIO(raw_bytes)) as img:
            fmt = (img.format or "UNKNOWN").lower()
            return img.width, img.height, fmt
    except Exception as exc:
        logger.debug("[Base64Downsampler] Probing metadata failed: %s", exc)
        return None
