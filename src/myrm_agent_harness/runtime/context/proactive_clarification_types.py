"""Types and schemas for proactive clarification, slot tracking, and convergence state machine.

[INPUT]
Conversational turn inputs, user intents, slot schema definitions, and action selections.

[OUTPUT]
Type-safe representations of slot states, clarification action chips,
dialogue convergence metrics, and execution gates.

[POS]
Core protocol benchmarked against Bairong BR-LLM-Proactive multi-turn slot filling architecture.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal


class SlotStateKind(StrEnum):
    """Lifecycle status of an individual intent slot."""
    EMPTY = "empty"
    INFERRED = "inferred"
    CONFIRMED = "confirmed"


class ConvergenceVerdict(StrEnum):
    """Dialogue progress and convergence evaluation verdict."""
    PROGRESSING = "progressing"
    STAGNANT = "stagnant"
    CONVERGED = "converged"
    ABORTED = "aborted"


@dataclass(frozen=True)
class IntentSlotSpec:
    """Specification of an expected slot parameter for a given intent."""
    name: str
    description: str
    required: bool = True
    expected_type: Literal["string", "number", "boolean", "choice"] = "string"
    allowed_choices: tuple[str, ...] = field(default_factory=tuple)
    min_confidence_threshold: float = 0.70


@dataclass(frozen=True)
class SlotValueRecord:
    """Current value and confidence score of an intent slot."""
    value: str | None
    state: SlotStateKind
    confidence_score: float = 0.0
    source_turn_idx: int = -1
    last_updated_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class ClarificationActionChip:
    """Interactive choice chip rendered in WebUI/Desktop for instant one-click clarification."""
    chip_id: str
    label: str
    target_slot_name: str
    slot_value: str
    is_recommended: bool = False


@dataclass(frozen=True)
class ClarificationRequestPayload:
    """Structured proactive clarification question with action chips."""
    question_text: str
    missing_slot_names: tuple[str, ...]
    action_chips: tuple[ClarificationActionChip, ...]
    turn_index: int
    suppress_tool_execution: bool = True


@dataclass(frozen=True)
class ConvergenceAuditSnapshot:
    """Metrics assessing dialogue convergence and stagnation across turns."""
    turn_index: int
    total_slots_count: int
    filled_slots_count: int
    confirmed_slots_count: int
    stagnant_turns_count: int
    verdict: ConvergenceVerdict
    summary_of_known_facts: dict[str, str] = field(default_factory=dict)
