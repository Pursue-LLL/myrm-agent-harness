"""Domain models and contracts for natural language memory feedback and live correction.

[INPUT]
- None (standard library only)

[OUTPUT]
- CorrectionIntentKind: Categorical intent of the natural language correction.
- MutationAction: Physical operation performed on memory state.
- CorrectionSlot: Extracted correction slots (negated belief vs new assertion).
- TargetNodeCandidate: Existing memory candidate targeted for mutation.
- LiveCorrectionMutationResult: Result of executing atomic mutation.
- CorrectionAckReceipt: High-level receipt with natural language acknowledgement.

[POS]
myrm_agent_harness.toolkits.memory.live_correction.models
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class CorrectionIntentKind(StrEnum):
    """Categorical intent detected from natural language user feedback."""

    PREFERENCE_UPDATE = "preference_update"
    FACT_SUPERSEDED = "fact_superseded"
    BEHAVIOR_RULE = "behavior_rule"
    RETRACT_MISTAKE = "retract_mistake"
    GENERAL_AMENDMENT = "general_amendment"


class MutationAction(StrEnum):
    """Atomic mutation operation executed on target memory items."""

    SUPERSEDE = "supersede"
    RETRACT = "retract"
    AMEND = "amend"
    CREATE_NOVEL = "create_novel"


@dataclass(frozen=True, slots=True)
class CorrectionSlot:
    """Extracted semantic slots from user correction utterance."""

    corrected_value: str
    negated_value: str | None = None
    subject: str | None = None
    intent: CorrectionIntentKind = CorrectionIntentKind.PREFERENCE_UPDATE
    confidence: float = 1.0
    raw_utterance: str = ""


@dataclass(frozen=True, slots=True)
class TargetNodeCandidate:
    """Existing memory item located as candidate for live correction."""

    memory_id: str
    content: str
    cube_id: str | None = None
    match_score: float = 1.0
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LiveCorrectionMutationResult:
    """Atomic execution result of a live correction mutation."""

    action: MutationAction
    target_memory_id: str | None
    new_memory_id: str | None
    status: str
    superseded_content: str | None = None
    new_content: str | None = None
    audit_trail: dict[str, str] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True, slots=True)
class CorrectionAckReceipt:
    """High-level receipt with user-facing acknowledgement text."""

    success: bool
    ack_message: str
    intent: CorrectionIntentKind
    slot: CorrectionSlot
    mutated_record: LiveCorrectionMutationResult | None = None
    processing_ms: float = 0.0
