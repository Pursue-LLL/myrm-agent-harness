"""Commitment type definitions — enums and Pydantic schemas.

Zero ORM or backend dependencies. Foundation layer for the commitment
tracking system: implicit user promises and follow-up items extracted
from conversations, automatically checked during heartbeat ticks.

[INPUT]
- pydantic::BaseModel (POS: Validation + serialization layer)
- datetime, uuid (POS: Standard library utilities)

[OUTPUT]
- CommitmentKind: 4 commitment categories (event/deadline/care/open_loop)
- CommitmentSensitivity: 3 sensitivity levels controlling thresholds
- CommitmentStatus: 5-state lifecycle (pending→sent→dismissed/snoozed/expired)
- CommitmentDueWindow: Time window for commitment delivery
- CommitmentRecord: Full commitment record with scope and lifecycle
- CommitmentCandidate: LLM extraction output before persistence

[POS]
Commitment type system foundation. Provides type-safe schema definitions
for implicit promise tracking extracted from conversations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


class CommitmentKind(StrEnum):
    """Four categories covering all follow-up patterns."""

    EVENT_CHECK_IN = "event_check_in"
    DEADLINE_CHECK = "deadline_check"
    CARE_CHECK_IN = "care_check_in"
    OPEN_LOOP = "open_loop"


class CommitmentSensitivity(StrEnum):
    """Controls confidence thresholds — care requires highest bar."""

    ROUTINE = "routine"
    PERSONAL = "personal"
    CARE = "care"


class CommitmentStatus(StrEnum):
    """Lifecycle: pending → sent/dismissed/snoozed/expired."""

    PENDING = "pending"
    SENT = "sent"
    DISMISSED = "dismissed"
    SNOOZED = "snoozed"
    EXPIRED = "expired"


def is_active_status(status: CommitmentStatus) -> bool:
    """Whether the commitment can still be delivered."""
    return status in (CommitmentStatus.PENDING, CommitmentStatus.SNOOZED)


class CommitmentDueWindow(BaseModel):
    """Time window for commitment delivery."""

    earliest_ms: int = Field(description="Earliest delivery time (epoch ms)")
    latest_ms: int = Field(description="Latest delivery time (epoch ms)")
    timezone: str = Field(default="UTC")


class CommitmentRecord(BaseModel):
    """Full commitment record with scope, content, and lifecycle state."""

    id: str = Field(default_factory=lambda: f"cm_{uuid4().hex[:16]}")
    agent_id: str
    user_id: str
    channel: str = Field(default="web")

    kind: CommitmentKind
    sensitivity: CommitmentSensitivity
    status: CommitmentStatus = CommitmentStatus.PENDING

    reason: str = Field(description="Why this commitment was created")
    suggested_text: str = Field(description="Natural text to send when due")
    dedupe_key: str = Field(description="Stable key for deduplication within scope")
    confidence: float = Field(ge=0.0, le=1.0)

    due_window: CommitmentDueWindow

    source_chat_id: str | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    attempts: int = 0
    last_attempt_at: datetime | None = None
    sent_at: datetime | None = None
    dismissed_at: datetime | None = None
    snoozed_until_ms: int | None = None
    expired_at: datetime | None = None


class CommitmentCandidate(BaseModel):
    """LLM extraction output — validated before persistence."""

    kind: CommitmentKind
    sensitivity: CommitmentSensitivity
    reason: str
    suggested_text: str
    dedupe_key: str
    confidence: float = Field(ge=0.0, le=1.0)
    due_window_earliest: str = Field(description="ISO timestamp string")
    due_window_latest: str | None = None
    due_window_timezone: str | None = None


class ExtractionBatchResult(BaseModel):
    """Structured output from LLM commitment extraction."""

    candidates: list[CommitmentCandidate] = Field(default_factory=list)
