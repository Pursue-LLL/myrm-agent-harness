"""Wiki cognitive map event types for human-readable log.md entries.

[INPUT]
- None (standalone enum and event dataclass)

[OUTPUT]
- WikiMapEventType: lifecycle event labels for cognitive map refresh
- WikiMapEvent: immutable event payload for log.md append

[POS]
Event taxonomy for OKF wiki/log.md entries. Used by compiler, linter, and server hooks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class WikiMapEventType(StrEnum):
    COMPILE = "compile"
    MAINTAIN = "maintain"
    IMPORT = "import"
    PENDING_APPROVE = "pending_approve"
    REPAIR_TYPES = "repair_types"
    RAW_SUPERSEDE = "raw_supersede"
    RAW_SECURITY = "raw_security"
    EVIDENCE_FORGOTTEN = "evidence_forgotten"
    EVIDENCE_RESTORED = "evidence_restored"


@dataclass(frozen=True, slots=True)
class WikiMapEvent:
    event_type: WikiMapEventType
    summary: str
    details: dict[str, object] = field(default_factory=dict)
