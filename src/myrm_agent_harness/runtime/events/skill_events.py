"""Skill runtime failure events.

[INPUT]
- runtime.events.bus::BaseEvent (POS: Event Bus Implementation)

[OUTPUT]
- SkillFailureCandidate: Candidate storage skill attributed to a runtime failure.
- SkillFailureEvent: Non-blocking framework event for skill-attributed tool failures.

[POS]
Framework-level skill failure event DTOs. They carry runtime evidence for business
layers without importing product, GUI, approval, or tenant concepts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .bus import BaseEvent


@dataclass(frozen=True, slots=True)
class SkillFailureCandidate:
    """Storage skill candidate that may have contributed to a tool failure."""

    skill_id: str
    skill_name: str
    confidence: float
    version: str | None = None
    storage_path: str | None = None
    evolution_locked: bool = False
    reason: str = ""


@dataclass(frozen=True, slots=True)
class SkillFailureEvent(BaseEvent):
    """Runtime failure event attributed to one or more loaded storage skills."""

    tool_name: str
    error_message: str
    error_signature: str
    candidates: tuple[SkillFailureCandidate, ...]
    tool_call_id: str = ""
    tool_args_hash: str = ""
    loop_kind: str | None = None
    session_id: str | None = None
    task_intent: str = ""
    occurred_at: float = field(default_factory=time.time)
