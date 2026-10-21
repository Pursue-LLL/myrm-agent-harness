"""Per-scope proof that a process was actually launched.

[INPUT]
- (none - stdlib only)

[OUTPUT]
- ExecutionEvidence: Mutable record that flips once any command or script was launched in its scope
- track_execution: Bind a fresh record to the current context for the duration of a block
- record_execution: Called by executors when they launch a process

[POS]
Lets a caller that must not trust a model's claim of having run something (the verifier's PASS gate)
ask whether the executor really launched a process. The record lives in a ContextVar, so tasks created
inside the scope share it while a parallel scope (a sibling verifier) keeps its own.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class ExecutionEvidence:
    """Whether a process was launched inside the tracked scope."""

    executed: bool = False


_ACTIVE_EVIDENCE: ContextVar[ExecutionEvidence | None] = ContextVar("_ACTIVE_EVIDENCE", default=None)


def record_execution() -> None:
    """Mark the active scope as having launched a process; a no-op outside any tracked scope."""
    evidence = _ACTIVE_EVIDENCE.get()
    if evidence is not None:
        evidence.executed = True


@contextmanager
def track_execution() -> Iterator[ExecutionEvidence]:
    """Track process launches made inside the block, including those of tasks it creates."""
    evidence = ExecutionEvidence()
    token = _ACTIVE_EVIDENCE.set(evidence)
    try:
        yield evidence
    finally:
        _ACTIVE_EVIDENCE.reset(token)
