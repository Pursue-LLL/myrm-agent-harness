"""Mempalace Inode Identity toolkit for directory synchronization.

Provides robust physical device/inode identification, directory rename detection,
and cross-volume sync safeguards to eliminate double-sync and phantom data loss.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.inode_identity.facade import (
    InodeIdentityFacade,
    get_inode_identity_facade,
)
from myrm_agent_harness.toolkits.memory.inode_identity.guard import (
    DirectoryIdentityGuard,
)
from myrm_agent_harness.toolkits.memory.inode_identity.models import (
    DeviceFilesystemKind,
    DirectoryIdentity,
    IdentityMatchKind,
    InodeResolutionResult,
    SyncGuardAction,
    SyncGuardDecision,
)
from myrm_agent_harness.toolkits.memory.inode_identity.resolver import (
    InodeIdentityResolver,
)

__all__ = [
    "DeviceFilesystemKind",
    "DirectoryIdentity",
    "DirectoryIdentityGuard",
    "IdentityMatchKind",
    "InodeIdentityFacade",
    "InodeIdentityResolver",
    "InodeResolutionResult",
    "SyncGuardAction",
    "SyncGuardDecision",
    "get_inode_identity_facade",
]
