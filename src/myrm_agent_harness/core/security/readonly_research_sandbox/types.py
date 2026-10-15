"""
[POS] src/myrm_agent_harness/core/security/readonly_research_sandbox/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] DEFAULT_READ_ONLY_TOOLS, ResearchModeEnum, LeaseStatusEnum, ReadOnlyLeaseRecord, WorkspaceSnapshot, EphemeralCowFileRecord, ReadOnlyShieldBadge, ReadOnlyResearchMetrics

Data structures and specifications for Read-Only Autonomous Research Lease & Immutable Snapshot Sandbox Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class EphemeralCowFileRecord:
    """Transient file written strictly into ephemeral in-memory CoW layer."""

    virtual_path: str
    file_bytes: bytes
    sha256_hash: str
    written_at: float


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """Cryptographic baseline snapshot of protected workspace prior to research lease."""

    snapshot_id: str
    session_id: str
    baseline_timestamp: float
    file_manifest_hashes: dict[str, str] = field(default_factory=dict)
    root_digest: str = ""


@dataclass(frozen=True)
class ReadOnlyShieldBadge:
    """Real-time UI security indicator badge."""

    is_read_only_active: bool
    active_lease_id: str | None
    research_mode: ResearchModeEnum
    cow_overlay_active: bool
    workspace_purity_verified: bool
    badge_label: str


@dataclass
class ReadOnlyResearchMetrics:
    """Cumulative operational metrics for read-only research sandbox subsystem."""

    total_leases_granted: int = 0
    active_leases_count: int = 0
    leases_revoked_count: int = 0
    write_attempts_blocked: int = 0
    ephemeral_cow_files_staged: int = 0
    overlays_purged_count: int = 0
    purity_verifications_count: int = 0
