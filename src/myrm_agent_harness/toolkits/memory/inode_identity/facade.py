"""Facade for directory inode identity resolution and sync arbitration."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.inode_identity.guard import (
    DirectoryIdentityGuard,
)
from myrm_agent_harness.toolkits.memory.inode_identity.models import (
    DirectoryIdentity,
    InodeResolutionResult,
    SyncGuardDecision,
)
from myrm_agent_harness.toolkits.memory.inode_identity.resolver import (
    InodeIdentityResolver,
)


class InodeIdentityFacade:
    """Unified entrypoint for filesystem inode identity verification."""

    def __init__(
        self,
        resolver: InodeIdentityResolver | None = None,
        guard: DirectoryIdentityGuard | None = None,
    ) -> None:
        self._resolver: InodeIdentityResolver = resolver or InodeIdentityResolver()
        self._guard: DirectoryIdentityGuard = guard or DirectoryIdentityGuard(self._resolver)

    def resolve(self, target_path: str) -> InodeResolutionResult:
        """Resolve physical device and inode identity for a directory path."""
        return self._resolver.resolve(target_path)

    def evaluate_sync(
        self,
        target_path: str,
        known_identities: list[DirectoryIdentity] | dict[str, DirectoryIdentity],
    ) -> SyncGuardDecision:
        """Arbitrate directory identity against registered workspaces."""
        return self._guard.evaluate(target_path, known_identities)


_FACADE_INSTANCE: InodeIdentityFacade | None = None


def get_inode_identity_facade() -> InodeIdentityFacade:
    """Obtain or initialize the global InodeIdentityFacade singleton."""
    global _FACADE_INSTANCE
    if _FACADE_INSTANCE is None:
        _FACADE_INSTANCE = InodeIdentityFacade()
    return _FACADE_INSTANCE
