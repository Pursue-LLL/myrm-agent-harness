"""Core data structures and types for Workspace Path RBAC & Denial Audit.

[INPUT]
- Path patterns, access modes, file actions, and enterprise identity metadata.

[OUTPUT]
- Strongly-typed verdicts, denial cards, and structured audit ledger records.

[POS]
- Harness core security contracts for granular filesystem isolation and write protection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PathAccessMode(StrEnum):
    """Filesystem path permissions mode."""

    RO = "ro"  # Read-only
    RW = "rw"  # Read-write
    NONE = "none"  # No access


class FileActionType(StrEnum):
    """Classified file operations subject to zero-trust inspection."""

    READ = "READ"
    DIRECT_WRITE = "DIRECT_WRITE"
    COPY_WRITE = "COPY_WRITE"
    MKDIR = "MKDIR"
    DELETE = "DELETE"

    @property
    def is_mutation(self) -> bool:
        """Return True if action modifies the filesystem."""
        return self in (
            FileActionType.DIRECT_WRITE,
            FileActionType.COPY_WRITE,
            FileActionType.MKDIR,
            FileActionType.DELETE,
        )


class WriteDenialReason(StrEnum):
    """Categorized root causes for write operation rejections."""

    READ_ONLY_PATH = "READ_ONLY_PATH"
    UNAUTHORIZED_PATH = "UNAUTHORIZED_PATH"
    TRIPLE_WRITE_DEFENSE_TRIGGERED = "TRIPLE_WRITE_DEFENSE_TRIGGERED"


@dataclass(frozen=True)
class PathRule:
    """Path permission rule."""

    pattern: str  # e.g. "raw_data/**", "inputs/*", "deliverables/**"
    mode: PathAccessMode = PathAccessMode.RO
    description: str = ""


@dataclass
class WorkspacePolicy:
    """Granular filesystem RBAC policy for a workspace or task."""

    policy_id: str
    user_identity: str
    project_root: str
    rules: list[PathRule] = field(default_factory=list)
    allowed_deliverables_dir: str = "deliverables"


@dataclass(frozen=True)
class WriteDenialCard:
    """Security denial notice card formatted for user interface and auto-recovery."""

    title: str
    message: str
    blocked_path: str
    action: str
    suggested_redirect_path: str


@dataclass(frozen=True)
class AccessCheckVerdict:
    """Evaluation verdict for an attempted file operation."""

    allowed: bool
    effective_mode: PathAccessMode
    violation_reason: str | None = None
    auto_reroute_hint: str | None = None
    denial_card: WriteDenialCard | None = None


@dataclass(frozen=True)
class AuditLedgerEntry:
    """Immutable audit record tracking filesystem operation or security denial."""

    entry_id: str
    timestamp: float
    agent_id: str
    session_id: str
    user_identity: str
    target_path: str
    action: FileActionType
    granted: bool
    violation_reason: str | None = None
