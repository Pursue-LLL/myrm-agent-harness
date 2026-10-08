"""Data types and schemas for Companion Relationship Safety Guard.

[INPUT]
- None.

[OUTPUT]
- Typed data models and enums for companion safety categories, contexts, and verdicts.

[POS]
- Harness core security module defining decorum and compliance boundaries for relationship-oriented AI companions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CompanionViolationCategory(StrEnum):
    """Categorized safety and compliance violations for relationship-oriented agent interactions."""

    ROMANTIC_EXPLOITATION = "romantic_exploitation"
    LATE_NIGHT_PRODDING = "late_night_prodding"
    EMOTIONAL_MONETIZATION = "emotional_monetization"
    RELATIONSHIP_JAILBREAK = "relationship_jailbreak"


@dataclass(frozen=True)
class CompanionGuardContext:
    """Evaluation input context for companion agent response review."""

    user_message: str
    candidate_response: str
    local_hour: int
    monetization_intent_present: bool = False


@dataclass(frozen=True)
class CompanionSafetyVerdict:
    """Outcome of companion relationship safety evaluation."""

    is_safe: bool
    violations: list[CompanionViolationCategory] = field(default_factory=list)
    risk_score: float = 0.0
    sanitized_response: str | None = None
    advisory_message: str | None = None
    is_late_night: bool = False
