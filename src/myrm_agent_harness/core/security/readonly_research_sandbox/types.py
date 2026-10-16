"""Data shapes of read-only research leases.

[INPUT]
- Standard library only (dataclasses, enum).

[OUTPUT]
- DEFAULT_READ_ONLY_TOOLS: built-in tools a lease permits by default
- ResearchModeEnum, LeaseStatusEnum: lease mode and lifecycle status
- ReadOnlyLeaseRecord: one session's lease
- ReadOnlyResearchMetrics: counters of grants, revocations and blocked calls

[POS]
Shared vocabulary of the lease manager and its facade.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# Built-in tools a read-only lease permits by default: reading files and searching/fetching the web.
# Every name must be a built-in tool flagged ``is_read_only`` in ``TOOL_SAFETY_METADATA``; memory, skill,
# browser and MCP reads are deliberately absent (callers needing them pass ``custom_allowed_tools``).
DEFAULT_READ_ONLY_TOOLS: tuple[str, ...] = (
    "file_read_tool",
    "grep_tool",
    "glob_tool",
    "web_search_tool",
    "web_fetch_tool",
)


class ResearchModeEnum(StrEnum):
    """Autonomous research operational mode."""

    GENERAL_INTERACTIVE = "GENERAL_INTERACTIVE"
    AUTONOMOUS_RESEARCH = "AUTONOMOUS_RESEARCH"
    BACKGROUND_STUDY = "BACKGROUND_STUDY"


class LeaseStatusEnum(StrEnum):
    """Lifecycle status of a read-only research lease."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


@dataclass(frozen=True)
class ReadOnlyLeaseRecord:
    """Exclusive read-only authority lease attached to an autonomous research session."""

    lease_id: str
    session_id: str
    research_mode: ResearchModeEnum
    granted_at: float
    expires_at: float
    allowed_tools: tuple[str, ...]
    status: LeaseStatusEnum = LeaseStatusEnum.ACTIVE


@dataclass
class ReadOnlyResearchMetrics:
    """Cumulative operational metrics for read-only research sandbox subsystem."""

    total_leases_granted: int = 0
    active_leases_count: int = 0
    leases_revoked_count: int = 0
    write_attempts_blocked: int = 0
