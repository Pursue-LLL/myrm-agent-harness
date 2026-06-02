"""Screenshot diff utilities — unified comparison system.

Provides both fast (dHash) and accurate (Canvas API) screenshot comparison.
"""

from .accurate_comparator import AccurateComparator
from .fast_comparator import FastComparator
from .screenshot_comparator import ScreenshotComparator
from .types import AccurateComparisonResult, ComparisonResult, FastComparisonResult

__all__ = [
    "AccurateComparator",
    "AccurateComparisonResult",
    "ComparisonResult",
    "FastComparator",
    "FastComparisonResult",
    "ScreenshotComparator",
]
