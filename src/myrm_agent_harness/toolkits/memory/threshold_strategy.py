"""Adaptive similarity-threshold strategies for memory retrieval.

[INPUT]
- (none)

[OUTPUT]
- AdaptiveThresholdStrategy: Protocol for adaptive similarity threshold strategies.
- CountBasedThresholdStrategy: Count-based adaptive threshold strategy with smooth transitions.

[POS]
Maps the size of a memory library to the similarity threshold used by retrieval.
"""

from __future__ import annotations

from typing import Protocol


class AdaptiveThresholdStrategy(Protocol):
    """Protocol for adaptive similarity threshold strategies.

    Allows dynamic threshold adjustment based on memory count to:
    - Lower thresholds for small libraries (improve recall)
    - Raise thresholds for large libraries (reduce noise)
    """

    def get_threshold(self, memory_count: int) -> float:
        """Get adaptive similarity threshold based on memory count.

        Args:
            memory_count: Total number of memories in the library

        Returns:
            Similarity threshold value (typically in range [0.4, 0.65])
        """
        ...


class CountBasedThresholdStrategy:
    """Count-based adaptive threshold strategy with smooth transitions.

    Threshold ranges:
    - <500 memories: 0.45 (small library, improve recall)
    - 500-2000: 0.50 (medium library, default BGE-M3 optimized)
    - 2000-5000: 0.55 (large library, reduce noise)
    - >5000: 0.60 (very large library, strict filtering)

    Uses smooth linear interpolation between thresholds to avoid sudden jumps.
    """

    def get_threshold(self, memory_count: int) -> float:
        """Calculate adaptive threshold with smooth transitions."""
        if memory_count < 500:
            return 0.45
        elif memory_count < 2000:
            ratio = (memory_count - 500) / (2000 - 500)
            return 0.45 + (0.50 - 0.45) * ratio
        elif memory_count < 5000:
            ratio = (memory_count - 2000) / (5000 - 2000)
            return 0.50 + (0.55 - 0.50) * ratio
        else:
            ratio = min((memory_count - 5000) / 5000, 1.0)
            return 0.55 + (0.60 - 0.55) * ratio
