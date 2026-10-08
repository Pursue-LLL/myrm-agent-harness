"""Type definitions and data models for sandbox log redaction and execution continuation audit.

[INPUT]
- None.

[OUTPUT]
- Typed dataclasses and literals for log redaction, heartbeats, and continuation audits.

[POS]
- Harness core security module for sandbox observability, privacy, and continuation reconciliation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class RedactionCategory(StrEnum):
    """Categories of sensitive credentials detected in logs and terminal streams."""

    API_KEY = "API_KEY"
    BEARER_TOKEN = "BEARER_TOKEN"
    PRIVATE_KEY = "PRIVATE_KEY"
    PASSWORD_ENV = "PASSWORD_ENV"
    URL_CREDENTIAL = "URL_CREDENTIAL"
    CUSTOM = "CUSTOM"


@dataclass(frozen=True)
class RedactionMatch:
    """Record of a single redacted token occurrence."""

    category: RedactionCategory
    matched_snippet: str
    replacement: str
    start: int
    end: int


@dataclass(frozen=True)
class RedactionResult:
    """Aggregated output of a log redaction pass."""

    original_length: int
    redacted_text: str
    redaction_count: int
    categories_redacted: list[RedactionCategory] = field(default_factory=list)


class ContinuationStatus(StrEnum):
    """Audit verification verdict status for execution continuations."""

    VALID = "VALID"
    STALE_HEARTBEAT = "STALE_HEARTBEAT"
    OWNERSHIP_MISMATCH = "OWNERSHIP_MISMATCH"
    TASK_TERMINATED = "TASK_TERMINATED"
    MISSING_ORIGIN_RUN = "MISSING_ORIGIN_RUN"


@dataclass(frozen=True)
class HeartbeatSignal:
    """A periodic heartbeat emission recorded from an active sandbox runner."""

    run_id: str
    timestamp: float
    seq: int
    status: Literal["running", "idle", "busy", "terminating", "completed", "failed"]
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RunRecord:
    """Registration record of an execution run attached to a task."""

    run_id: str
    task_id: str
    assignee_agent_id: str
    is_terminal: bool
    started_at: float
    last_heartbeat_timestamp: float | None = None
    last_heartbeat_seq: int = 0


@dataclass(frozen=True)
class ContinuationAuditVerdict:
    """Evaluation result determining whether an execution can safely continue."""

    is_resumable: bool
    status: ContinuationStatus
    task_id: str
    proposed_run_id: str
    resume_source_run_id: str | None
    reconciliation_reason: str
    last_heartbeat_age_sec: float | None
