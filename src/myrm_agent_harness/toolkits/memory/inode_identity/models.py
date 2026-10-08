"""Domain models and enums for directory inode identity verification.

Provides immutable data structures representing physical directory identity,
resolution outcomes, and sync guard decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DeviceFilesystemKind(StrEnum):
    """Filesystem host environment classification."""

    POSIX = "posix"
    WINDOWS = "windows"
    FALLBACK_VIRTUAL = "fallback_virtual"


class IdentityMatchKind(StrEnum):
    """Semantic match classification for evaluated sync directories."""

    EXACT_MATCH = "exact_match"
    MOVED_OR_RENAMED = "moved_or_renamed"
    INODE_REUSED = "inode_reused"
    BRAND_NEW = "brand_new"


class SyncGuardAction(StrEnum):
    """Operational action emitted by directory identity guard."""

    PROCEED_INCREMENTAL = "proceed_incremental"
    RELOCATE_AND_PROCEED = "relocate_and_proceed"
    REBUILD_WARNING = "rebuild_warning"
    REGISTER_NEW = "register_new"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class DirectoryIdentity:
    """Immutable physical identity tuple of a synced directory."""

    canonical_path: str
    device_id: int
    inode_id: int
    birth_time_ns: int
    root_signature: str
    fs_kind: DeviceFilesystemKind
    is_symlink: bool = False
    physical_key: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "physical_key",
            f"{self.device_id}:{self.inode_id}",
        )


@dataclass(frozen=True)
class InodeResolutionResult:
    """Outcome of attempting to resolve physical directory identity."""

    real_path: str
    is_accessible: bool
    is_directory: bool
    identity: DirectoryIdentity | None = None
    is_symlink: bool = False
    error_message: str | None = None


@dataclass(frozen=True)
class SyncGuardDecision:
    """Final arbitration decision generated before syncing workspace memory."""

    action: SyncGuardAction
    match_kind: IdentityMatchKind
    reason: str
    old_path: str | None
    new_path: str
    physical_key: str
    needs_database_relocation: bool
    identity: DirectoryIdentity | None = None
