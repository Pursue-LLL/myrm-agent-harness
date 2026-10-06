# [POS] src/myrm_agent_harness/toolkits/memory/override_stack/types.py
# [INPUT] enum, dataclasses, typing, myrm_agent_harness.toolkits.memory.types.ProceduralMemory
# [OUTPUT] PriorityLevel, EphemeralBypassRecord, PlaybookOverrideEvaluation

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.types import ProceduralMemory


class PriorityLevel(StrEnum):
    """Immutable priority hierarchy for behavioral directive resolution."""

    LEVEL_1_TURN_OVERRIDE = "level_1_turn_override"
    LEVEL_2_SESSION_DECISION = "level_2_session_decision"
    LEVEL_3_PROCEDURAL_PLAYBOOK = "level_3_procedural_playbook"


@dataclass(frozen=True)
class EphemeralBypassRecord:
    """Audit record for a procedural rule temporarily bypassed in the current turn."""

    rule_id: str
    rule_action: str
    conflicting_clause: str
    bypass_reason: str
    bypassed_in_current_turn: bool = True


@dataclass(frozen=True)
class PlaybookOverrideEvaluation:
    """Outcome of priority stack resolution and ephemeral bypass gating."""

    active_rules: tuple["ProceduralMemory", ...]
    bypassed_records: tuple[EphemeralBypassRecord, ...]
    injected_context_note: str
    has_conflicts: bool = field(default=False)
