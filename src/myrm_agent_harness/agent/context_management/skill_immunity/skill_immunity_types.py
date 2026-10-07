"""Strongly typed contracts for Active Skill Context Compaction Immunity and Re-Anchor Suite (Item 213).

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- SkillImmunityScope: Level of compaction immunity protection.
- ActiveSkillSpec: Strongly typed descriptor of an active skill with SOP rules and system prompt patches.
- ReAnchorAnchorPosition: Injection target position for post-compaction re-anchoring.
- ReAnchorOutcome: Detailed telemetry outcome of re-anchoring active skills into compressed contexts.
- SkillImmunityConfig: Tunable configurations for immunity and XML rendering.

[POS]
- Prevents rule dilution and behavioral drift across 50+ turns by shielding active skill SOPs
- from lossy compaction and re-anchoring deterministic skill specifications into prompt frames.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class SkillImmunityScope(str, enum.Enum):
    """Immunity level shielding skill content from compaction dilution."""

    IMMUNE_CORE = "immune_core"
    IMMUNE_TEMPORARY = "immune_temporary"
    STANDARD_SUMMARIZABLE = "standard_summarizable"


class ReAnchorAnchorPosition(str, enum.Enum):
    """Placement position for re-anchored skills in the compacted message sequence."""

    AFTER_SYSTEM = "after_system"
    BETWEEN_SUMMARY_AND_TAIL = "between_summary_and_tail"
    PROMPT_TAIL = "prompt_tail"


@dataclass(frozen=True, slots=True)
class ActiveSkillSpec:
    """Strongly typed descriptor representing an active skill that requires zero compaction decay."""

    skill_id: str
    name: str
    sop_rules: list[str] = field(default_factory=list)
    scope: SkillImmunityScope = SkillImmunityScope.IMMUNE_CORE
    system_prompt_patch: str = ""
    parameters_schema: dict[str, object] = field(default_factory=dict)
    activated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        """Serializes skill spec to dictionary."""
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "sop_rules": list(self.sop_rules),
            "scope": self.scope.value,
            "system_prompt_patch": self.system_prompt_patch,
            "parameters_schema": dict(self.parameters_schema),
            "activated_at": self.activated_at,
        }


@dataclass(frozen=True, slots=True)
class ReAnchorOutcome:
    """Telemetry report recording outcome of post-compaction skill re-anchoring."""

    re_anchored: bool
    skill_count: int
    re_anchored_xml: str
    cache_fingerprint: str
    re_anchor_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        """Serializes re-anchor outcome to dictionary."""
        return {
            "re_anchored": self.re_anchored,
            "skill_count": self.skill_count,
            "re_anchored_xml": self.re_anchored_xml,
            "cache_fingerprint": self.cache_fingerprint,
            "re_anchor_duration_ms": self.re_anchor_duration_ms,
        }


@dataclass(slots=True)
class SkillImmunityConfig:
    """Configuration governing skill immunity shields and prompt re-anchor formatting."""

    enabled: bool = True
    xml_tag: str = "active_skills"
    anchor_position: ReAnchorAnchorPosition = ReAnchorAnchorPosition.BETWEEN_SUMMARY_AND_TAIL
    deterministic_sorting: bool = True
