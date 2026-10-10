"""Domain models for Project Experience & ADR Flywheel suite.

[INPUT]
- Execution traces, error logs, architectural decisions, and module entities.

[OUTPUT]
- ExperienceKind, EngineeringExperience, MinefieldAlert, FlywheelIngestResult.

[POS]
- Domain models for Item 154 ProjectExperienceAndADRFlywheelSuite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ExperienceKind(str, Enum):
    """Categorization of engineering experience items."""

    BUG_EXPERIENCE = "bug_experience"
    ARCHITECTURAL_DECISION = "architectural_decision"
    CONVENTION_RULE = "convention_rule"


@dataclass(frozen=True)
class EngineeringExperience:
    """Structured engineering experience record binding cause and convention."""

    experience_id: str
    kind: ExperienceKind
    target_entity: str  # Module, table, API, or system component identifier
    trigger_condition: str  # Environmental preconditions or invocation patterns
    root_cause_or_rationale: str  # Underlying cause of failure or decision justification
    convention_or_remedy: str  # Enforced rule or effective fix
    created_date: str  # YYYY-MM-DD
    tags: tuple[str, ...] = ()
    confidence: float = 1.0


@dataclass(frozen=True)
class MinefieldAlert:
    """Pre-sniffed warning surfaced before agent execution to prevent repeat errors."""

    entity_matched: str
    experience_id: str
    kind: ExperienceKind
    warning_message: str
    convention_to_follow: str
    severity: str = "warning"  # critical | warning | info


@dataclass(frozen=True)
class FlywheelIngestResult:
    """Outcome of ingesting experience into the flywheel and dongle."""

    experience_id: str
    kind: ExperienceKind
    target_entity: str
    bound_dongle_block_id: str | None = None
    persisted: bool = True
    message: str = ""
