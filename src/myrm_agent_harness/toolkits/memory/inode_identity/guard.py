"""Directory identity sync guard and collision arbitrator.

Prevents double-sync disasters, automatically detects directory rename/move events,
and guards against volume recreations or cross-device collisions.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.inode_identity.models import (
    DirectoryIdentity,
    IdentityMatchKind,
    SyncGuardAction,
    SyncGuardDecision,
)
from myrm_agent_harness.toolkits.memory.inode_identity.resolver import (
    InodeIdentityResolver,
)


class DirectoryIdentityGuard:
    """Arbitrates directory identity during workspace synchronization."""

    def __init__(self, resolver: InodeIdentityResolver | None = None) -> None:
        self._resolver: InodeIdentityResolver = resolver or InodeIdentityResolver()

    def evaluate(
        self,
        target_path: str,
        known_identities: list[DirectoryIdentity] | dict[str, DirectoryIdentity],
    ) -> SyncGuardDecision:
        """Evaluate a target sync path against recorded directory identities.

        Parameters
        ----------
        target_path:
            The path requested for synchronization.
        known_identities:
            Previously registered DirectoryIdentity instances (either a list or
            a dictionary keyed by physical_key or canonical_path).

        Returns
        -------
        SyncGuardDecision
            Operational directive indicating whether to proceed incrementally,
            relocate existing records, issue a rebuild warning, or register anew.
        """
        resolution = self._resolver.resolve(target_path)
        if not resolution.is_accessible or not resolution.is_directory or resolution.identity is None:
            return SyncGuardDecision(
                action=SyncGuardAction.BLOCKED,
                match_kind=IdentityMatchKind.BRAND_NEW,
                reason=resolution.error_message or "Path is inaccessible or not a directory",
                old_path=None,
                new_path=target_path,
                physical_key="",
                needs_database_relocation=False,
                identity=None,
            )

        current_ident = resolution.identity
        registry_by_key, registry_by_path = self._index_known_identities(known_identities)

        # 1. Match by physical tuple (device_id:inode_id)
        if current_ident.physical_key in registry_by_key:
            recorded = registry_by_key[current_ident.physical_key]
            if recorded.canonical_path == current_ident.canonical_path:
                return SyncGuardDecision(
                    action=SyncGuardAction.PROCEED_INCREMENTAL,
                    match_kind=IdentityMatchKind.EXACT_MATCH,
                    reason="Exact physical identity and canonical path match",
                    old_path=recorded.canonical_path,
                    new_path=current_ident.canonical_path,
                    physical_key=current_ident.physical_key,
                    needs_database_relocation=False,
                    identity=current_ident,
                )

            # Move or rename detected!
            return SyncGuardDecision(
                action=SyncGuardAction.RELOCATE_AND_PROCEED,
                match_kind=IdentityMatchKind.MOVED_OR_RENAMED,
                reason=(
                    f"Directory moved or renamed from '{recorded.canonical_path}' "
                    f"to '{current_ident.canonical_path}'. Preserving memory lineage."
                ),
                old_path=recorded.canonical_path,
                new_path=current_ident.canonical_path,
                physical_key=current_ident.physical_key,
                needs_database_relocation=True,
                identity=current_ident,
            )

        # 2. Check if the canonical path was previously recorded with a different inode
        if current_ident.canonical_path in registry_by_path:
            old_recorded = registry_by_path[current_ident.canonical_path]
            return SyncGuardDecision(
                action=SyncGuardAction.REBUILD_WARNING,
                match_kind=IdentityMatchKind.INODE_REUSED,
                reason=(
                    f"Path '{current_ident.canonical_path}' has a new physical identity "
                    f"(previous {old_recorded.physical_key}, now {current_ident.physical_key}). "
                    "Directory may have been recreated or moved across volume mounts."
                ),
                old_path=old_recorded.canonical_path,
                new_path=current_ident.canonical_path,
                physical_key=current_ident.physical_key,
                needs_database_relocation=False,
                identity=current_ident,
            )

        # 3. Completely new workspace
        return SyncGuardDecision(
            action=SyncGuardAction.REGISTER_NEW,
            match_kind=IdentityMatchKind.BRAND_NEW,
            reason="Unrecognized directory, registering new physical identity",
            old_path=None,
            new_path=current_ident.canonical_path,
            physical_key=current_ident.physical_key,
            needs_database_relocation=False,
            identity=current_ident,
        )

    def _index_known_identities(
        self,
        identities: list[DirectoryIdentity] | dict[str, DirectoryIdentity],
    ) -> tuple[dict[str, DirectoryIdentity], dict[str, DirectoryIdentity]]:
        """Index known identities by physical_key and canonical_path."""
        items: list[DirectoryIdentity]
        if isinstance(identities, dict):
            items = list(identities.values())
        else:
            items = identities

        by_key: dict[str, DirectoryIdentity] = {}
        by_path: dict[str, DirectoryIdentity] = {}

        for item in items:
            by_key[item.physical_key] = item
            by_path[item.canonical_path] = item

        return by_key, by_path
