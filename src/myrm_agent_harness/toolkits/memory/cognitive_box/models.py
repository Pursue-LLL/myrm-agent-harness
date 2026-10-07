"""[POS]: src/myrm_agent_harness/toolkits/memory/cognitive_box/models.py
[INPUT]: None (domain contracts and dataclasses).
[OUTPUT]: CognitiveLayerKind, IntakeDecisionKind, CognitiveMemoryEntry, IntakeEvaluationReport, CognitiveBoxSnapshot.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class CognitiveLayerKind(StrEnum):
    """The four distinct cognitive context layers defined by Hermes architecture."""

    IDENTITY = "identity"
    USER_PROFILE = "user_profile"
    ENVIRONMENT = "environment"
    LESSONS_RULES = "lessons_rules"


class IntakeDecisionKind(StrEnum):
    """Strict memory intake screening decision."""

    ADMIT = "admit"
    DROP_NOISE = "drop_noise"
    DROP_TRANSIENT = "drop_transient"
    UPDATE_EXISTING = "update_existing"


@dataclass(frozen=True)
class CognitiveMemoryEntry:
    """A durable item recorded in one of the cognitive memory layers."""

    id: str
    layer: CognitiveLayerKind
    content: str
    confidence: float
    tags: list[str] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0
    source_session: str | None = None


@dataclass(frozen=True)
class IntakeEvaluationReport:
    """Audit evaluation report produced by the strict memory intake filter."""

    decision: IntakeDecisionKind
    layer: CognitiveLayerKind | None
    confidence: float
    reason: str
    sanitized_content: str
    existing_entry_id: str | None = None


@dataclass(frozen=True)
class CognitiveBoxSnapshot:
    """Full snapshot of the four-layer cognitive memory box."""

    timestamp: float
    total_count: int
    counts_by_layer: dict[str, int]
    entries: list[CognitiveMemoryEntry]
