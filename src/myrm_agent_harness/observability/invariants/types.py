"""Runtime Invariant Type Definitions and Protocols.

[INPUT]
- None (Standard library dataclasses, enum, typing)

[OUTPUT]
- InvariantSeverity: Severity level for invariant violations (ERROR, WARN)
- InvariantViolation: Immutable data structure capturing violation details
- InvariantCheckerProtocol: Typing protocol for invariant checker callables

[POS]
Type contracts and protocols for framework-level runtime invariant assertion system.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol, runtime_checkable


class InvariantSeverity(str, Enum):
    """Severity of a detected invariant violation."""

    ERROR = "ERROR"
    WARN = "WARN"


@dataclass(frozen=True)
class InvariantViolation:
    """Detailed record of an invariant check failure.

    Attributes:
        code: Stable diagnostic code, default is 'INVARIANT'.
        package_name: Name of the subsystem or package registering the invariant.
        invariant_name: Descriptive unique identifier for the invariant rule.
        message: Human-readable explanation of the exact consistency breach.
        severity: InvariantSeverity level (ERROR triggers fail-fast in strict mode).
        details: Optional structured metadata or offending entity snapshot.
        occurred_at: Timestamp when the breach was evaluated.
    """

    package_name: str
    invariant_name: str
    message: str
    code: str = "INVARIANT"
    severity: InvariantSeverity = InvariantSeverity.ERROR
    details: dict[str, object] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class InvariantCheckerProtocol(Protocol):
    """Callable contract for an invariant validator."""

    def __call__(self, context: object) -> list[InvariantViolation]:
        """Evaluate context and return list of violations (empty if valid)."""
        ...


InvariantInstaller = Callable[[], None]
