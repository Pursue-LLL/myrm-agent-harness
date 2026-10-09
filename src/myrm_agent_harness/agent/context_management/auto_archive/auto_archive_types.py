"""Domain contracts and data models for account-wide idle chat auto-archive policy.

[INPUT]
- None (pure domain models and primitive types).

[OUTPUT]
- Exports ArchiveExemptionReason, ArchiveEligibilityVerdict, ChatSessionMetadata,
  AutoArchivePolicyConfig, ArchiveEvaluationResult, and ArchiveSweepSummary.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.auto_archive
- Module: auto_archive_types.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence, Tuple


class ArchiveExemptionReason(str, Enum):
    """Specific cause determining exemption or eligibility for auto-archive."""

    NONE = "none"
    DISABLED = "disabled"
    PINNED = "pinned"
    ACTIVE_TURN_RUNNING = "active_turn_running"
    USER_CREATED_EXEMPTED = "user_created_exempted"
    NOT_IDLE = "not_idle"
    ALREADY_ARCHIVED = "already_archived"


class ArchiveEligibilityVerdict(str, Enum):
    """Binary determination produced by policy evaluation."""

    ELIGIBLE = "eligible"
    EXEMPT = "exempt"


@dataclass(frozen=True)
class ChatSessionMetadata:
    """Snapshot attributes of a candidate chat session evaluated for archiving."""

    chat_id: str
    last_active_timestamp: float
    is_pinned: bool = False
    is_user_created: bool = True
    has_running_task: bool = False
    is_archived: bool = False


@dataclass(frozen=True)
class AutoArchivePolicyConfig:
    """Account-wide parameters governing automatic session archiving."""

    enabled: bool = False
    idle_threshold_seconds: int = 86400 * 7  # 7 days
    include_user_created: bool = True
    min_idle_threshold_seconds: int = 3600  # 1 hour
    max_idle_threshold_seconds: int = 86400 * 365  # 1 year

    def get_clamped_threshold(self) -> int:
        """Returns the idle threshold clamped within safety bounds."""
        return max(
            self.min_idle_threshold_seconds,
            min(self.idle_threshold_seconds, self.max_idle_threshold_seconds),
        )


@dataclass(frozen=True)
class ArchiveEvaluationResult:
    """Evaluation verdict and diagnostic reasoning for a single chat session."""

    chat_id: str
    verdict: ArchiveEligibilityVerdict
    reason: ArchiveExemptionReason
    idle_duration_seconds: float
    diagnostic_message: str


@dataclass(frozen=True)
class ArchiveSweepSummary:
    """Aggregated statistics resulting from a background archive sweep."""

    total_scanned: int
    eligible_count: int
    archived_count: int
    exempt_breakdown: Tuple[Tuple[str, int], ...] = field(default_factory=tuple)
    elapsed_seconds: float = 0.0
