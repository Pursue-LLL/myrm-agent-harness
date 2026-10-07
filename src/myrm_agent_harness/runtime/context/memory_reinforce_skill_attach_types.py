"""Types and data models for memory rule reinforcement emphasis gate and mid-session skill attachment.

Provides models for high-priority directive tagging, attention decay suppression,
and runtime non-blocking skill and tool definitions hot-attachment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ReinforcementPriorityKind(StrEnum):
    """Priority level for memory rule reinforcement in model attention space."""

    NORMAL = "normal"
    HIGH_ATTENTION_PRIORITY = "high_attention_priority"
    PINNED_SYSTEM_DIRECTIVE = "pinned_system_directive"


@dataclass(frozen=True)
class ReinforcedMemoryRule:
    """Memory or system rule with attention boost metadata and decay counters."""

    rule_id: str
    rule_content: str
    category: str
    priority: ReinforcementPriorityKind
    reinforce_count: int
    last_reinforced_at: float
    decay_suppression_rounds: int
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DynamicSkillAttachment:
    """Skill definition and exported tool schemas attached during a live session."""

    skill_id: str
    skill_name: str
    description: str
    tool_definitions: tuple[str, ...]
    attached_at_turn: int
    active: bool = True
    parameters_schema: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptEmphasisInjectionPayload:
    """Synthesized context injection payload for next turn inference."""

    session_id: str
    system_emphasis_block: str
    active_attached_skills: tuple[DynamicSkillAttachment, ...]
    effective_rules_count: int
    timestamp: float
