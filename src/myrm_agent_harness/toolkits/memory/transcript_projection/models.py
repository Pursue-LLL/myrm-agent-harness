"""Domain models for SQLite transcript projection and adoption disambiguation.

[INPUT]
- Raw transcript entries, session messages, timestamp values, and bootstrap specifications.

[OUTPUT]
- TranscriptEntry, SessionMessage, BootstrapContext, BootstrapResult, AdoptionDecision.

[POS]
- Core models and contracts for Item 150 SqliteTranscriptProjectionSuite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AdoptionStatus(str, Enum):
    """Adoption resolution status for a message-to-transcript link."""

    ADOPTED_UNIQUE = "adopted_unique"
    ADOPTED_BY_TIMESTAMP = "adopted_by_timestamp"
    UNSTAMPED_TWIN_CONFLICT = "unstamped_twin_conflict"
    UNSTAMPED_UNKNOWN_TIME = "unstamped_unknown_time"
    UNSTAMPED_NO_MATCH = "unstamped_no_match"


@dataclass(frozen=True)
class TranscriptEntry:
    """Entry stored in the SQLite transcript source-of-truth table."""

    entry_id: str
    session_id: str
    seq: int
    role: str
    content: str
    created_at_ms: int | None = None
    parent_id: str | None = None


@dataclass(frozen=True)
class SessionMessage:
    """Message projected into the working session memory."""

    message_id: str
    session_id: str
    seq: int
    role: str
    content: str
    timestamp_ms: int | None = None
    transcript_entry_id: str | None = None


@dataclass(frozen=True)
class AdoptionDecision:
    """Outcome of attempting to reconcile a live message with candidate transcript entries."""

    message_id: str
    transcript_entry_id: str | None
    status: AdoptionStatus
    reason: str


@dataclass(frozen=True)
class BootstrapContext:
    """Parameters for running a cold-start projection bootstrap."""

    session_id: str
    session_key: str
    agent_id: str = "main"
    tolerance_ms: int = 2000


@dataclass(frozen=True)
class BootstrapResult:
    """Result of cold-start transcript projection bootstrap."""

    session_id: str
    bootstrapped: bool
    imported_messages: int
    already_bootstrapped: bool
    decisions: tuple[AdoptionDecision, ...] = ()
