"""Type definitions for Scoped Folder Permission Dialog and Sandbox Dynamic Mount Suite.

[POS] src/myrm_agent_harness/core/security/scoped_folder_sandbox_mount/types.py
[INPUT] enum, dataclasses
[OUTPUT] FolderAccessMode, MountLifecyclePolicy, ScopedFolderGrant, SensitivePathCheckResult, DynamicMountSpec
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FolderAccessMode(StrEnum):
    """Access privilege level granted to a host folder."""

    READ_ONLY = "READ_ONLY"
    READ_WRITE = "READ_WRITE"


class MountLifecyclePolicy(StrEnum):
    """Lifecycle retention policy for the dynamic sandbox mount projection."""

    EPHEMERAL_PER_SESSION = "EPHEMERAL_PER_SESSION"
    PERSISTENT_UNTIL_REVOKED = "PERSISTENT_UNTIL_REVOKED"


@dataclass(slots=True, frozen=True)
class ScopedFolderGrant:
    """Security-scoped permission grant authorizing sandbox projection of a specific host folder."""

    grant_id: str
    folder_path: str
    alias_slug: str
    access_mode: FolderAccessMode
    lifecycle: MountLifecyclePolicy
    sandbox_mount_path: str
    granted_at: float
    expires_at: float | None = None
    is_revoked: bool = False
    revoked_at: float | None = None


@dataclass(slots=True, frozen=True)
class SensitivePathCheckResult:
    """Evaluation result verifying whether a path violates system safety blacklists."""

    is_blocked: bool
    resolved_path: str
    matched_rule: str | None = None
    reason: str | None = None


@dataclass(slots=True, frozen=True)
class DynamicMountSpec:
    """Executable mount specification for the container/sandbox virtualization driver."""

    source_host_path: str
    sandbox_target_path: str
    read_only: bool
    grant_id: str
