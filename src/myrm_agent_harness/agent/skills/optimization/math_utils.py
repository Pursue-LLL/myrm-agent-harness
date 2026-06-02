"""Statistical utility functions for skill quality aggregation

[INPUT]
- (none)

[OUTPUT]
- sample_std: Calculate sample standard deviation (Bessel's correction:...
- percentile: Calculate percentile from a pre-sorted list using linear ...

[POS]
Statistical utility functions for skill quality aggregation
"""

from __future__ import annotations


def sample_std(values: list[float]) -> float:
    """Calculate sample standard deviation (Bessel's correction: N-1 denominator)

    Args:
        values: List of numeric values (requires at least 2 elements)

    Returns:
        Sample standard deviation, 0.0 if fewer than 2 values
    """
    if len(values) < 2:
        return 0.0

    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    return variance**0.5


def percentile(sorted_values: list[float], p: float) -> float:
    """Calculate percentile from a pre-sorted list using linear interpolation

    Args:
        sorted_values: Pre-sorted list of numeric values (ascending)
        p: Percentile value (0-100)

    Returns:
        Interpolated percentile value, 0.0 if empty
    """
    if not sorted_values:
        return 0.0

    k = (len(sorted_values) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_values) else f

    if f == c:
        return sorted_values[f]

    return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)
