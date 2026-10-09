"""Types and data contracts for corrupt session degradation and auto-healing.

[INPUT]
- None (pure type definitions and immutable data contracts).

[OUTPUT]
- Exports enumerations and dataclasses for session restoration status,
  corrupt record archives, salvaged messages, restoration outcomes, and configuration.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.corrupt_session_healing
- Module: healing_types.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional, Sequence


class RestorationStatus(str, Enum):
    """Status indicating how a session restoration request was resolved."""

    RESTORED_CLEAN = "restored_clean"
    SALVAGED_PARTIAL = "salvaged_partial"
    HEALED_FRESH_FALLBACK = "healed_fresh_fallback"
    UNRECOVERABLE = "unrecoverable"


@dataclass(frozen=True)
class SalvagedMessageItem:
    """An individual message entry successfully recovered from a corrupted payload."""

    message_id: str
    role: str
    content: str
    salvaged_index: int


@dataclass(frozen=True)
class CorruptRecordArchive:
    """Metadata detailing the containment and quarantine of a corrupted session snapshot."""

    corrupted_session_id: str
    archive_path: str
    error_diagnostic: str
    salvaged_message_count: int
    archived_at_epoch: float
    content_hash: str


@dataclass(frozen=True)
class RestorationOutcome:
    """Result of restoring a session, incorporating salvage or fresh healing fallback."""

    original_session_id: str
    active_session_id: str
    status: RestorationStatus
    salvaged_messages: Sequence[SalvagedMessageItem] = field(default_factory=tuple)
    is_fresh_session: bool = False
    diagnostic_message: str = ""


@dataclass(frozen=True)
class HealingSuiteConfig:
    """Configuration options governing corrupt session quarantine and auto-healing."""

    archive_directory: str = "/tmp/sandbox/corrupt_sessions"
    attempt_partial_salvage: bool = True
    auto_activate_fresh_session: bool = True
    fresh_session_prefix: str = "fresh-healed"
    max_salvaged_messages: int = 500
