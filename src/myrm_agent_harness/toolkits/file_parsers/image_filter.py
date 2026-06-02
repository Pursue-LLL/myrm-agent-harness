"""
[INPUT]
images: list[str] (Base64 PNG/JPEG)

[OUTPUT]
ImageAblationFilter: Provides multi-stage heuristic image filtering (size, aspect ratio, monochrome, MD5 de-duplication)
ImageExtractionTrace: Diagnostic metrics for the filtering process

[POS]
Smart image ablation filter. Intercepts UI noise, decorative lines, tiny logos,
and duplicate images in multimodal RAG pipelines, significantly improving LLM prompt SNR.
"""

import base64
import hashlib
import io
import logging
from dataclasses import dataclass, field

from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class ImageExtractionTrace:
    """Extraction trace tracking how many images were processed, kept, and dropped."""

    total_processed: int = 0
    kept_count: int = 0
    dropped_count: int = 0
    drop_reasons: dict[str, int] = field(default_factory=dict)
    # Allows downstream tracing of specific dropped image details if needed
    dropped_signatures: list[str] = field(default_factory=list)


class ImageAblationFilter:
    """
    Implements a multi-stage cascading filter to eliminate visual noise.
    Level 1: Pure Physical/Heuristic checks (Size, Aspect Ratio, Entropy).
    Level 2: Cache checks (MD5 dedup) to prevent processing the same IEEE logo 100 times.
    (Level 3 VLM validator is injected via composition where VLM is available).
    """

    def __init__(
        self,
        min_width: int = 50,
        min_height: int = 50,
        extreme_aspect_ratio: float = 12.0,
    ):
        self.min_width = min_width
        self.min_height = min_height
        self.extreme_aspect_ratio = extreme_aspect_ratio
        # Runtime dedup cache for a single parsing session
        self._hash_cache: set[str] = set()

    def filter_images(self, images_b64: list[str]) -> tuple[list[str], ImageExtractionTrace]:
        """
        Runs the physical and cache heuristic pipelines.
        Returns a tuple of (kept base64 images, ExtractionTrace).
        """
        trace = ImageExtractionTrace(total_processed=len(images_b64))
        kept: list[str] = []

        if not images_b64:
            return kept, trace

        for b64_str in images_b64:
            try:
                img_data = base64.b64decode(b64_str)

                # MD5 Dedup filter
                img_hash = hashlib.md5(img_data).hexdigest()
                if img_hash in self._hash_cache:
                    trace.dropped_count += 1
                    trace.drop_reasons["duplicate_cached"] = trace.drop_reasons.get("duplicate_cached", 0) + 1
                    continue

                img = Image.open(io.BytesIO(img_data))
                w, h = img.size

                # 1. Size heuristic (drop tiny UI icons, bullets, tracking pixels)
                if w < self.min_width or h < self.min_height:
                    trace.dropped_count += 1
                    trace.drop_reasons["size_too_small"] = trace.drop_reasons.get("size_too_small", 0) + 1
                    continue

                # 2. Aspect ratio heuristic
                aspect_ratio = w / h if h != 0 else 0
                if aspect_ratio > self.extreme_aspect_ratio or aspect_ratio < (1.0 / self.extreme_aspect_ratio):
                    # Potential horizontal/vertical line.
                    # Real OCR check could be plugged in here if heavy dependencies are enabled.
                    trace.dropped_count += 1
                    trace.drop_reasons["extreme_aspect_ratio"] = trace.drop_reasons.get("extreme_aspect_ratio", 0) + 1
                    continue

                # 3. Entropy / Blank monochrome detection (Drop pure black lines, white masks)
                try:
                    # Convert to grayscale to test for flat colors
                    gray_img = img.convert("L")
                    extrema = gray_img.getextrema()
                    # if min brightness == max brightness, the image is entirely one solid color
                    if extrema and isinstance(extrema, tuple) and extrema[0] == extrema[1]:
                        trace.dropped_count += 1
                        trace.drop_reasons["monochrome_or_blank"] = trace.drop_reasons.get("monochrome_or_blank", 0) + 1
                        continue
                except Exception:
                    pass

                # Image is meaningful (structurally)!
                self._hash_cache.add(img_hash)
                kept.append(b64_str)
                trace.kept_count += 1

            except Exception as e:
                # Invalid base64 or corrupt image -> drop
                logger.warning(f"Filter caught invalid image stream: {e}")
                trace.dropped_count += 1
                trace.drop_reasons["invalid_image"] = trace.drop_reasons.get("invalid_image", 0) + 1

        return kept, trace
