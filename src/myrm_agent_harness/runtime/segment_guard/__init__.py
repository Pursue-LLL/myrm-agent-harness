"""Bounded segment execution primitives: verified appends and step budgets.

The job supervisor runs long-running cron work as bounded segments so a crash can
resume from a checkpoint instead of repeating side effects. That contract needs two
guards: an append that refuses to write over a tail it did not expect (concurrent
truncation) and a step counter that forces a segment to yield before it runs too long.

[INPUT]
- .appender::AtomicSegmentAppender (POS: 尾部校验原子追加)
- .budget::BoundedSegmentBudget (POS: 步数预算计量)

[OUTPUT]
- AtomicSegmentAppender, TailMismatchError, BoundedSegmentBudget, StepBudgetExceededError

[POS]
Segment-execution guard subpackage. Pure primitives with no executor dependency, so a
host can import them without pulling the agent runtime.
"""

from .appender import AtomicSegmentAppender, TailMismatchError
from .budget import BoundedSegmentBudget, StepBudgetExceededError

__all__ = [
    "AtomicSegmentAppender",
    "BoundedSegmentBudget",
    "StepBudgetExceededError",
    "TailMismatchError",
]
