"""Unified type system for screenshot comparison.


[INPUT]
- (none — type definitions only)

[OUTPUT]
- ComparisonResult: Protocol for all comparison results
- FastComparisonResult: dHash comparison result (dataclass)
- AccurateComparisonResult: Canvas API comparison result (dataclass)
- validate_screenshot_input: Shared validation for base64 screenshot inputs

[POS]
Unified type system for screenshot diff. Defines Protocol and dataclass types for type safety.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import Literal, Protocol

MAX_BASE64_SIZE = 10 * 1024 * 1024
MAX_IMAGE_DIMENSION = 4096


def validate_screenshot_input(screenshot_b64: str, param_name: str) -> bytes:
    """Validate and decode screenshot base64 input.

    Args:
        screenshot_b64: Base64-encoded screenshot
        param_name: Parameter name for error messages

    Returns:
        Decoded image bytes

    Raises:
        ValueError: If input is invalid (too large, invalid base64, invalid image)
    """
    if len(screenshot_b64) > MAX_BASE64_SIZE:
        raise ValueError(
            f"{param_name} too large: {len(screenshot_b64)} bytes (max {MAX_BASE64_SIZE // 1024 // 1024}MB)"
        )

    try:
        image_bytes = base64.b64decode(screenshot_b64, validate=True)
    except Exception as exc:
        raise ValueError(f"{param_name} is not valid base64") from exc

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size

        if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
            raise ValueError(
                f"{param_name} dimensions too large: {width}x{height} (max {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION})"
            )

        img.verify()
    except ValueError:
        raise
    except ImportError:
        pass
    except Exception as exc:
        raise ValueError(f"{param_name} is not a valid image") from exc

    return image_bytes


class ComparisonResult(Protocol):
    """Screenshot comparison result protocol.

    All comparison algorithms must return objects implementing this protocol.
    """

    @property
    def similarity(self) -> float:
        """Similarity score (0.0-1.0, where 1.0 = identical)."""
        ...

    @property
    def is_significant_change(self) -> bool:
        """Whether the change is considered significant."""
        ...

    @property
    def algorithm(self) -> str:
        """Algorithm identifier (e.g., 'dhash', 'canvas_pixel')."""
        ...

    def to_llm_message(self) -> str:
        """Convert result to LLM-friendly string representation."""
        ...


@dataclass(frozen=True, slots=True)
class FastComparisonResult:
    """Fast comparison result using perceptual hash (dHash).

    Attributes:
        similarity: Similarity score (0.0-1.0), calculated from Hamming distance
        hamming_distance: Number of different bits (0-64)
        is_significant_change: Whether similarity is below threshold
        algorithm: Always 'dhash'
    """

    similarity: float
    hamming_distance: int
    is_significant_change: bool
    algorithm: Literal["dhash"] = "dhash"

    def to_llm_message(self) -> str:
        """Convert result to LLM-friendly string representation."""
        status = "SIGNIFICANT CHANGE" if self.is_significant_change else "SIMILAR"
        return (
            f"Screenshot comparison (fast): {status}\n"
            f"Similarity: {self.similarity:.1%} (hamming distance: {self.hamming_distance}/64)\n"
            f"Algorithm: dHash (perceptual hash, ~2ms)"
        )


@dataclass(frozen=True, slots=True)
class AccurateComparisonResult:
    """Accurate pixel-level comparison result using Canvas API.

    Attributes:
        similarity: Similarity score (0.0-1.0), calculated as 1 - mismatch_percentage/100
        total_pixels: Total number of pixels compared
        different_pixels: Number of different pixels
        mismatch_percentage: Percentage of pixels that differ (0-100)
        diff_image_b64: Base64-encoded PNG with red-marked differences
        dimension_mismatch: Whether images have different dimensions
        is_significant_change: Whether mismatch percentage exceeds threshold
        algorithm: Always 'canvas_pixel'
    """

    similarity: float
    total_pixels: int
    different_pixels: int
    mismatch_percentage: float
    diff_image_b64: str
    dimension_mismatch: bool
    is_significant_change: bool
    algorithm: Literal["canvas_pixel"] = "canvas_pixel"

    def to_llm_message(self) -> str:
        """Convert result to LLM-friendly string representation."""
        status = "SIGNIFICANT CHANGE" if self.is_significant_change else "SIMILAR"
        dim_note = " ( dimension mismatch — images have different sizes)" if self.dimension_mismatch else ""

        return (
            f"Screenshot comparison (accurate): {status}\n"
            f"Similarity: {self.similarity:.1%}\n"
            f"Mismatch: {self.mismatch_percentage:.2f}% "
            f"({self.different_pixels:,} of {self.total_pixels:,} pixels){dim_note}\n"
            f"Diff image: {len(self.diff_image_b64)} bytes base64 PNG (red = changed pixels)\n"
            f"Algorithm: Canvas API pixel-level comparison (~100ms)"
        )
