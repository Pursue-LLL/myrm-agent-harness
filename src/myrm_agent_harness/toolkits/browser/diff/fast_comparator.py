"""Fast screenshot comparison using perceptual hash (dHash).


[INPUT]
- PIL::Image (POS: Python image processing library)
- base64 (POS: Base64 encode/decode)
- .types (POS: FastComparisonResult)

[OUTPUT]
- FastComparator: fast screenshot comparator

[POS]
Fast screenshot comparison tool. Uses dHash (difference hash) algorithm for O(1) visual similarity detection.

Algorithm:
1. Resize image to 9x8 pixels (preserves structural features)
2. Convert to grayscale
3. Compute horizontal gradient (adjacent pixel differences)
4. Generate 64-bit hash value
5. Hamming distance for similarity calculation

Performance: ~2ms
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from .types import FastComparisonResult

try:
    from PIL import Image
except (ImportError, TypeError):
    Image = None  # type: ignore[assignment]

_MAX_BASE64_SIZE = 10 * 1024 * 1024
_MAX_IMAGE_DIMENSION = 4096


def _validate_screenshot_input(screenshot_b64: str, param_name: str) -> bytes:
    """Validate and decode screenshot base64 input.

    Args:
        screenshot_b64: Base64-encoded screenshot
        param_name: Parameter name for error messages

    Returns:
        Decoded image bytes

    Raises:
        ValueError: If input is invalid (too large, invalid base64, invalid image)
    """
    if len(screenshot_b64) > _MAX_BASE64_SIZE:
        raise ValueError(
            f"{param_name} too large: {len(screenshot_b64)} bytes (max {_MAX_BASE64_SIZE // 1024 // 1024}MB)"
        )

    try:
        image_bytes = base64.b64decode(screenshot_b64, validate=True)
    except Exception as exc:
        raise ValueError(f"{param_name} is not valid base64") from exc

    if Image is None:
        raise ImportError("Pillow is required for FastComparator. Install: uv sync --all-extras")

    try:
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size

        if width > _MAX_IMAGE_DIMENSION or height > _MAX_IMAGE_DIMENSION:
            raise ValueError(
                f"{param_name} dimensions too large: {width}x{height} "
                f"(max {_MAX_IMAGE_DIMENSION}x{_MAX_IMAGE_DIMENSION})"
            )

        img.verify()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"{param_name} is not a valid image") from exc

    return image_bytes


@dataclass
class FastComparator:
    """Fast screenshot comparator using dHash algorithm.

    Uses Difference Hash (dHash) to generate 64-bit perceptual hash from
    horizontal gradient features, enabling O(1) visual similarity detection.

    Use cases:
    - Quick detection of visual changes
    - Animation/loading completion detection
    - Visual regression testing

    NOT suitable for:
    - Precise pixel-level comparison (use AccurateComparator)
    - Locating specific changed regions (dHash only provides global similarity)

    Attributes:
        similarity_threshold: Minimum similarity (0.0-1.0) to consider images similar.
            Values below this threshold indicate significant change. Default: 0.9
    """

    similarity_threshold: float = 0.9

    def __post_init__(self) -> None:
        """Validate dependencies."""
        if Image is None:
            raise ImportError("Pillow is required for FastComparator. Install: uv sync --all-extras")
        if not 0.0 <= self.similarity_threshold <= 1.0:
            raise ValueError(f"similarity_threshold must be in [0.0, 1.0], got {self.similarity_threshold}")

    def compare(self, screenshot1: str, screenshot2: str) -> FastComparisonResult:
        """Compare two screenshots (base64 encoded).

        Args:
            screenshot1: First screenshot as base64 string
            screenshot2: Second screenshot as base64 string

        Returns:
            FastComparisonResult with similarity and hamming distance

        Raises:
            ValueError: If input is invalid (too large, invalid base64, invalid image)
        """
        img1_bytes = _validate_screenshot_input(screenshot1, "screenshot1")
        img2_bytes = _validate_screenshot_input(screenshot2, "screenshot2")

        hash1 = self._compute_hash_from_bytes(img1_bytes)
        hash2 = self._compute_hash_from_bytes(img2_bytes)

        hamming = self._hamming_distance(hash1, hash2)
        similarity = 1 - (hamming / 64.0)
        is_significant = similarity < self.similarity_threshold

        return FastComparisonResult(
            similarity=similarity,
            hamming_distance=hamming,
            is_significant_change=is_significant,
        )

    def _compute_hash_from_bytes(self, image_bytes: bytes) -> int:
        """Compute dHash (Difference Hash) from image bytes.

        Algorithm steps:
        1. Load PIL Image from bytes
        2. Convert to grayscale
        3. Resize to 9x8 pixels
        4. Calculate horizontal gradient (compare adjacent pixels per row)
        5. Generate 64-bit hash

        Args:
            image_bytes: Raw image bytes (already validated)

        Returns:
            64-bit integer hash value
        """
        img = Image.open(io.BytesIO(image_bytes))

        img = img.convert("L")  # type: ignore[assignment]

        img = img.resize((9, 8), Image.Resampling.LANCZOS)  # type: ignore[assignment]

        try:
            pixels = img.get_flattened_data()  # type: ignore[attr-defined]
        except AttributeError:
            pixels = list(img.getdata())  # Fallback for older Pillow versions

        hash_value = 0
        for row in range(8):
            for col in range(8):
                idx = row * 9 + col
                left_pixel = int(pixels[idx])
                right_pixel = int(pixels[idx + 1])

                if left_pixel < right_pixel:
                    bit_pos = row * 8 + col
                    hash_value |= 1 << bit_pos

        return hash_value

    @staticmethod
    def _hamming_distance(hash1: int, hash2: int) -> int:
        """Calculate Hamming distance between two hash values.

        Args:
            hash1: First hash value
            hash2: Second hash value

        Returns:
            Hamming distance (0-64, number of different bits)
        """
        xor = hash1 ^ hash2
        return bin(xor).count("1")

    @staticmethod
    def from_bytes(image_bytes: bytes) -> int:
        """Compute dHash from raw image bytes (for non-base64 input).

        Args:
            image_bytes: Raw image bytes (no validation performed)

        Returns:
            64-bit integer hash value

        Raises:
            ImportError: If Pillow is not installed
        """
        if Image is None:
            raise ImportError("Pillow is required for FastComparator")

        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)  # type: ignore[assignment]
        try:
            pixels = img.get_flattened_data()  # type: ignore[attr-defined]
        except AttributeError:
            pixels = list(img.getdata())  # Fallback for older Pillow versions

        hash_value = 0
        for row in range(8):
            for col in range(8):
                idx = row * 9 + col
                left_pixel = int(pixels[idx])
                right_pixel = int(pixels[idx + 1])

                if left_pixel < right_pixel:
                    bit_pos = row * 8 + col
                    hash_value |= 1 << bit_pos

        return hash_value
