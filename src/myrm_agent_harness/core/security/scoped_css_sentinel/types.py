"""Types and data structures for Scoped CSS Isolation and Parallel Micro-Agent Boundary Sentinel."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


def _utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(UTC)


class CssViolationSeverity(StrEnum):
    """Severity classification of CSS rule isolation violations."""

    CRITICAL_REJECTION = "critical_rejection"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class GlobalSelectorViolation:
    """Diagnostic detail of a prohibited global selector detected in a micro-agent patch."""

    selector: str
    reason: str
    severity: CssViolationSeverity = CssViolationSeverity.CRITICAL_REJECTION
    line_number: int | None = None


@dataclass(frozen=True, slots=True)
class CssScopingResult:
    """Outcome of parsing and rewriting CSS into an isolated scoped component namespace."""

    is_valid: bool
    original_css: str
    scoped_css: str
    scope_id: str
    violations: list[GlobalSelectorViolation]
    rules_rewritten: int


@dataclass(frozen=True, slots=True)
class ConcurrentStylePatch:
    """Style patch submitted by a concurrent micro-agent targeting a UI sub-component."""

    agent_id: str
    component_target_id: str
    css_content: str
    timestamp: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, slots=True)
class ConflictCheckResult:
    """Outcome of validating multiple concurrent agent style patches for boundary collisions."""

    has_conflict: bool
    conflicting_agents: list[str]
    reason: str
    merged_scoped_css: str | None
