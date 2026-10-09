"""Algebraic utilities and geometry operations on bitemporal half-open intervals.

[POS]
Provides mathematical intersection, containment, and point-in-time evaluation
for temporal coordinates strictly adhering to half-open interval semantics [start, end).

[INPUT]
- myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.models.BitemporalCoordinates
- myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.models.TimeInterval

[OUTPUT]
- create_interval
- intersect_intervals
- span_intervals
- is_bitemporal_point_active
- shift_interval
"""

from __future__ import annotations

from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.models import (
    BitemporalCoordinates,
    TimeInterval,
)


def create_interval(start: float, end: float | None = None) -> TimeInterval:
    """Convenience factory to construct a strictly validated half-open interval [start, end)."""
    return TimeInterval(start=start, end=end)


def intersect_intervals(a: TimeInterval, b: TimeInterval) -> TimeInterval | None:
    """Computes the intersection of two half-open intervals [start, end).

    Returns:
        New TimeInterval if overlapping, or None if disjoint.
    """
    max_start = max(a.start, b.start)
    a_end = float("inf") if a.end is None else a.end
    b_end = float("inf") if b.end is None else b.end
    min_end = min(a_end, b_end)

    if max_start < min_end:
        result_end = None if min_end == float("inf") else min_end
        return TimeInterval(start=max_start, end=result_end)
    return None


def span_intervals(intervals: Sequence[TimeInterval]) -> TimeInterval | None:
    """Computes the minimal bounding interval covering all provided intervals."""
    if not intervals:
        return None

    min_start = min(inv.start for inv in intervals)
    any_unbounded = any(inv.is_unbounded_end for inv in intervals)

    if any_unbounded:
        return TimeInterval(start=min_start, end=None)

    max_end = max(inv.end for inv in intervals if inv.end is not None)
    return TimeInterval(start=min_start, end=max_end)


def is_bitemporal_point_active(
    bitemporal: BitemporalCoordinates,
    valid_time: float,
    known_time: float,
) -> bool:
    """Evaluates whether coordinates hold at a specific bitemporal point in time."""
    return bitemporal.is_active_at(valid_time=valid_time, known_time=known_time)


def shift_interval(interval: TimeInterval, delta: float) -> TimeInterval:
    """Shifts an interval by delta seconds forward (or backward if delta < 0)."""
    new_end = None if interval.end is None else interval.end + delta
    return TimeInterval(start=interval.start + delta, end=new_end)
