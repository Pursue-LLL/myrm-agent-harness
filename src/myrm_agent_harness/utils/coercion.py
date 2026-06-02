"""Defensive numeric coercion utilities.

Provides `parse_float`, `parse_int`, and `parse_timeout` — each handles
inf / nan / negative / non-numeric inputs gracefully, always returning a
safe default within the specified bounds.

[INPUT]
- (none)

[OUTPUT]
- parse_float: defensive float coercion
- parse_int: defensive int coercion
- parse_timeout: timeout-specific float coercion (default 0.1-3600s)

[POS]
Defensive numeric coercion utilities.
"""

from __future__ import annotations

import math


def parse_float(
    val: object,
    default: float,
    *,
    min_val: float | None = None,
    max_val: float | None = None,
) -> float:
    """Defensive float coercion — handles inf/nan/negative/non-numeric inputs.

    Args:
        val: Input value to coerce.
        default: Fallback value for any failure (must itself be finite).
        min_val: Optional lower bound (inclusive). Values below are clamped up.
        max_val: Optional upper bound (inclusive). Values above are clamped down.

    Returns:
        A finite float within [min_val, max_val] if bounds are set.

    Raises:
        Nothing — all errors are swallowed and *default* is returned.
    """
    if val is None or isinstance(val, bool):
        return default

    try:
        result = float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default

    if math.isnan(result) or math.isinf(result):
        return default

    if min_val is not None and result < min_val:
        return min_val
    if max_val is not None and result > max_val:
        return max_val
    return result


def parse_int(
    val: object,
    default: int,
    *,
    min_val: int | None = None,
    max_val: int | None = None,
) -> int:
    """Defensive int coercion — handles inf/nan/float/negative/non-numeric inputs.

    Booleans are rejected (returns *default*) because accepting bool → int
    masks config errors (e.g. ``True`` becoming 1 for max_turns).

    Args:
        val: Input value to coerce.
        default: Fallback value for any failure.
        min_val: Optional lower bound (inclusive).
        max_val: Optional upper bound (inclusive).

    Returns:
        An int within [min_val, max_val] if bounds are set.
    """
    if val is None or isinstance(val, bool):
        return default

    try:
        result = int(float(val))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default

    if min_val is not None and result < min_val:
        return min_val
    if max_val is not None and result > max_val:
        return max_val
    return result


def parse_timeout(
    val: object,
    default: float = 120.0,
    *,
    min_val: float = 0.1,
    max_val: float = 3600.0,
) -> float:
    """Timeout-specific defensive float coercion.

    Shorthand for ``parse_float`` with default bounds [0.1, 3600] seconds.
    """
    return parse_float(val, default, min_val=min_val, max_val=max_val)


__all__ = ["parse_float", "parse_int", "parse_timeout"]
