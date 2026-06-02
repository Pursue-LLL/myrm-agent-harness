"""Curator result types.

[INPUT]
- backends.skills.types::SkillLifecycleStatus (POS: 技能生命周期状态枚举)
- backends.skills.forgetting_strategy::ForgettingReason (POS: Skill forgetting / curator strategies)

[OUTPUT]
- CuratorTransition: Single skill lifecycle transition record.
- CuratorRunResult: Aggregate result of a curator sweep.

[POS]
Data types for the Skill Curator engine output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CuratorTransition:
    """Records a single skill lifecycle transition performed by the Curator."""

    skill_name: str
    skill_path: str
    from_status: str
    to_status: str
    reason_type: str
    reason_message: str
    timestamp: datetime


@dataclass(slots=True)
class CuratorRunResult:
    """Aggregate result of a single Curator sweep."""

    transitions: list[CuratorTransition] = field(default_factory=list)
    skills_scanned: int = 0
    skipped_pinned: int = 0
    skipped_protected: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_transitions(self) -> int:
        return len(self.transitions)

    @property
    def stale_count(self) -> int:
        return sum(1 for t in self.transitions if t.to_status == "stale")

    @property
    def archived_count(self) -> int:
        return sum(1 for t in self.transitions if t.to_status == "archived")
