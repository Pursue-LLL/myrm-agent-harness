"""Data types and schemas for framework-bound clarify tool and ambiguity resolver.

Defines typed options, impact levels, structured cards, and ambiguity detection reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ImpactLevelKind(StrEnum):
    """Potential impact or risk level of the decision requiring clarification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL_DESTRUCTIVE = "critical_destructive"


class AmbiguityCategory(StrEnum):
    """Categorical reason why user instruction requires proactive clarification."""

    MISSING_PARAMETER = "missing_parameter"
    MULTIPLE_APPROACHES = "multiple_approaches"
    DESTRUCTIVE_BOUNDARY = "destructive_boundary"
    USER_PREFERENCE = "user_preference"


@dataclass(frozen=True)
class ClarifyOptionItem:
    """A concrete selectable choice presented to the user on the clarify card."""

    option_id: str
    label: str
    description: str = ""
    is_recommended: bool = False


@dataclass(frozen=True)
class ClarifyToolParams:
    """Invocation arguments supplied to framework-bound clarify_tool."""

    question: str
    options: tuple[ClarifyOptionItem, ...]
    allow_custom_input: bool = True
    allow_multiple: bool = False
    impact_level: ImpactLevelKind = ImpactLevelKind.LOW
    category: AmbiguityCategory = AmbiguityCategory.MISSING_PARAMETER
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ClarifyResolutionResult:
    """User choice or automated test resolution returned to the agent."""

    selected_option_ids: tuple[str, ...]
    custom_input: str | None = None
    confirmed: bool = True
    resolution_summary: str = ""
    timestamp: float = 0.0


@dataclass(frozen=True)
class AmbiguityDetectionReport:
    """Diagnostic report produced by active ambiguity detector on raw instructions."""

    is_ambiguous: bool
    category: AmbiguityCategory
    confidence: float
    missing_elements: tuple[str, ...]
    suggested_clarify_params: ClarifyToolParams | None = None
