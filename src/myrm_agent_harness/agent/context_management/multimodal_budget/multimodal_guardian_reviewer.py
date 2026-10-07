"""Multi-modal Guardian screening image payloads for format validity, size caps, and aspect bounds.

Prevents decompression bombs, malformed files, and adversarial extreme aspect ratios
from destabilizing context budgeting and visual reasoning pipelines.
"""

from __future__ import annotations

from typing import Sequence

from .multimodal_budget_types import (
    GuardianReviewResult,
    GuardianVerdictKind,
    ImageArtifactDescriptor,
)


class MultiModalGuardianReviewer:
    """Pre-flight security and integrity screener for image attachments."""

    _SUPPORTED_FORMATS: frozenset[str] = frozenset({"png", "jpg", "jpeg", "webp", "gif"})
    MAX_FILE_SIZE_BYTES: int = 20 * 1024 * 1024  # 20 MiB
    MAX_ASPECT_RATIO: float = 16.0  # Max long:short ratio
    MIN_DIMENSION: int = 16
    MAX_DIMENSION: int = 8192

    def review_image(self, descriptor: ImageArtifactDescriptor) -> GuardianReviewResult:
        """Screen image descriptor against format, dimension, and aspect ratio safety invariants."""
        # 1. Format verification
        clean_fmt = descriptor.format.strip().lower().lstrip(".")
        if clean_fmt not in self._SUPPORTED_FORMATS:
            return GuardianReviewResult(
                image_id=descriptor.image_id,
                verdict=GuardianVerdictKind.REJECT_UNSUPPORTED_FORMAT,
                is_safe=False,
                reason=f"Unsupported image format '{descriptor.format}'. Supported: {sorted(self._SUPPORTED_FORMATS)}.",
            )

        # 2. File size cap
        if descriptor.size_bytes > self.MAX_FILE_SIZE_BYTES:
            return GuardianReviewResult(
                image_id=descriptor.image_id,
                verdict=GuardianVerdictKind.REJECT_SIZE_LIMIT,
                is_safe=False,
                reason=f"Image size {descriptor.size_bytes:,} bytes exceeds maximum limit of {self.MAX_FILE_SIZE_BYTES:,} bytes.",
            )

        # 3. Dimension boundaries
        w, h = descriptor.resolution.width, descriptor.resolution.height
        if w < self.MIN_DIMENSION or h < self.MIN_DIMENSION or w > self.MAX_DIMENSION or h > self.MAX_DIMENSION:
            return GuardianReviewResult(
                image_id=descriptor.image_id,
                verdict=GuardianVerdictKind.REJECT_INVALID_DIMENSIONS,
                is_safe=False,
                reason=f"Image dimensions ({w}x{h}) outside allowed bounds [{self.MIN_DIMENSION}..{self.MAX_DIMENSION}].",
            )

        # 4. Aspect ratio defense
        aspect_ratio = max(w, h) / max(1, min(w, h))
        if aspect_ratio > self.MAX_ASPECT_RATIO:
            return GuardianReviewResult(
                image_id=descriptor.image_id,
                verdict=GuardianVerdictKind.REJECT_EXTREME_ASPECT_RATIO,
                is_safe=False,
                reason=f"Extreme aspect ratio {aspect_ratio:.1f}:1 exceeds safe bound {self.MAX_ASPECT_RATIO}:1.",
            )

        return GuardianReviewResult(
            image_id=descriptor.image_id,
            verdict=GuardianVerdictKind.PASS,
            is_safe=True,
            reason="Image passed Guardian pre-flight screening.",
        )

    def review_batch(self, descriptors: Sequence[ImageArtifactDescriptor]) -> list[GuardianReviewResult]:
        """Screen multiple image descriptors sequentially."""
        return [self.review_image(desc) for desc in descriptors]
