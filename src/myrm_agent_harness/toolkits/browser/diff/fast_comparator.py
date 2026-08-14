"""Fast screenshot comparison using perceptual hash (dHash).


[INPUT]
- PIL::Image (POS: Python image processing library)
- .types (POS: FastComparisonResult, validate_screenshot_input)

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

import io
from dataclasses import dataclass

from .types import FastComparisonResult, validate_screenshot_input

try:
    from PIL import Image
except (ImportError, TypeError):
    Image = None  # type: ignore[assignment]


def _dhash(image_bytes: bytes) -> int:
    """Compute dHash (Difference Hash) from image bytes.

    Algorithm: resize to 9x8 grayscale, compute horizontal gradient,
    generate 64-bit hash from adjacent pixel comparisons.

    Args:
        image_bytes: Raw image bytes

    Returns:
        64-bit integer hash value
    """
    img = Image.open(io.BytesIO(image_bytes))
    img = img.convert("L")  # type: ignore[assignment]
    img = img.resize((9, 8), Image.Resampling.LANCZOS)  # type: ignore[assignment]

    try:
        pixels = img.get_flattened_data()  # type: ignore[attr-defined]
    except AttributeError:
        pixels = list(img.getdata())

    hash_value = 0
    for row in range(8):
        for col in range(8):
            idx = row * 9 + col
            if int(pixels[idx]) < int(pixels[idx + 1]):
                hash_value |= 1 << (row * 8 + col)
    return hash_value


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
        img1_bytes = validate_screenshot_input(screenshot1, "screenshot1")
        img2_bytes = validate_screenshot_input(screenshot2, "screenshot2")

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
        """Compute dHash from image bytes. Delegates to module-level `_dhash`."""
        return _dhash(image_bytes)

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
        return _dhash(image_bytes)
