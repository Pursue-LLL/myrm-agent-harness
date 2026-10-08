"""Dynamic Sandbox Mount Manager for security-scoped folder projection.

[POS] src/myrm_agent_harness/core/security/scoped_folder_sandbox_mount/dynamic_mount_manager.py
[INPUT] time, uuid, re, pathlib, myrm_agent_harness.core.security.scoped_folder_sandbox_mount.types, myrm_agent_harness.core.security.scoped_folder_sandbox_mount.sensitive_blacklist
[OUTPUT] DynamicSandboxMountManager
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from pathlib import Path
from typing import Final

from myrm_agent_harness.core.security.scoped_folder_sandbox_mount.sensitive_blacklist import (
    SensitivePathGuard,
)
from myrm_agent_harness.core.security.scoped_folder_sandbox_mount.types import (
    DynamicMountSpec,
    FolderAccessMode,
    MountLifecyclePolicy,
    ScopedFolderGrant,
    SensitivePathCheckResult,
)

logger: Final[logging.Logger] = logging.getLogger(__name__)


class DynamicSandboxMountManager:
    """Manages security-scoped folder authorization leases and on-demand sandbox projection mount points."""

    def __init__(
        self,
        sandbox_base_mount: str = "/workspace/granted",
        path_guard: SensitivePathGuard | None = None,
    ) -> None:
        self._sandbox_base_mount = sandbox_base_mount.rstrip("/")
        self._path_guard = path_guard or SensitivePathGuard()
        self._grants: dict[str, ScopedFolderGrant] = {}

    def grant_folder_access(
        self,
        folder_path: str,
        access_mode: FolderAccessMode = FolderAccessMode.READ_ONLY,
        lifecycle: MountLifecyclePolicy = MountLifecyclePolicy.EPHEMERAL_PER_SESSION,
        lease_seconds: float | None = 3600.0,
        alias_slug: str | None = None,
    ) -> ScopedFolderGrant:
        """Authorize a folder for sandbox projection after passing strict sensitive blacklist checks."""
        # 1. Verify path safety
        check = self._path_guard.validate_path(folder_path)
        if check.is_blocked:
            msg = f"Path '{folder_path}' is blocked by security policy: {check.reason} ({check.matched_rule})"
            raise PermissionError(msg)

        resolved_folder = Path(check.resolved_path)
        if not resolved_folder.exists() or not resolved_folder.is_dir():
            msg = f"Path '{folder_path}' does not exist or is not a directory."
            raise ValueError(msg)

        # 2. Derive sanitized alias slug
        slug = alias_slug or resolved_folder.name or "folder"
        sanitized_slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", slug).strip("_") or "folder"

        # Unique grant ID and sandbox mount path
        grant_id = f"grant-{uuid.uuid4().hex[:10]}"
        sandbox_mount_path = f"{self._sandbox_base_mount}/{sanitized_slug}"

        now = time.time()
        expires_at = (now + lease_seconds) if lease_seconds else None

        grant = ScopedFolderGrant(
            grant_id=grant_id,
            folder_path=str(resolved_folder),
            alias_slug=sanitized_slug,
            access_mode=access_mode,
            lifecycle=lifecycle,
            sandbox_mount_path=sandbox_mount_path,
            granted_at=now,
            expires_at=expires_at,
            is_revoked=False,
        )

        self._grants[grant_id] = grant
        logger.info(
            "Granted scoped folder projection grant=%s path='%s' mount='%s' mode=%s",
            grant_id,
            resolved_folder,
            sandbox_mount_path,
            access_mode.value,
        )
        return grant

    def get_mount_spec(self, grant_id: str) -> DynamicMountSpec | None:
        """Derive container mount specification for an active, valid grant."""
        grant = self._get_active_grant(grant_id)
        if grant is None:
            return None

        return DynamicMountSpec(
            source_host_path=grant.folder_path,
            sandbox_target_path=grant.sandbox_mount_path,
            read_only=grant.access_mode == FolderAccessMode.READ_ONLY,
            grant_id=grant.grant_id,
        )

    def revoke_grant(self, grant_id: str) -> bool:
        """Immediately revoke a folder grant, tearing down its projection."""
        grant = self._grants.get(grant_id)
        if grant is None or grant.is_revoked:
            return False

        updated = ScopedFolderGrant(
            grant_id=grant.grant_id,
            folder_path=grant.folder_path,
            alias_slug=grant.alias_slug,
            access_mode=grant.access_mode,
            lifecycle=grant.lifecycle,
            sandbox_mount_path=grant.sandbox_mount_path,
            granted_at=grant.granted_at,
            expires_at=grant.expires_at,
            is_revoked=True,
            revoked_at=time.time(),
        )
        self._grants[grant_id] = updated
        logger.info("Revoked folder grant %s for path '%s'", grant_id, grant.folder_path)
        return True

    def validate_path_safety(self, path: str) -> SensitivePathCheckResult:
        """Inspect safety of a candidate host directory prior to user dialog confirmation."""
        return self._path_guard.validate_path(path)

    def list_active_grants(self) -> list[ScopedFolderGrant]:
        """List currently valid and unexpired folder grants."""
        active: list[ScopedFolderGrant] = []
        for grant_id in list(self._grants.keys()):
            g = self._get_active_grant(grant_id)
            if g is not None:
                active.append(g)
        return active

    def list_all_grants(self) -> list[ScopedFolderGrant]:
        """List all grants including revoked or expired historical entries."""
        return list(self._grants.values())

    def _get_active_grant(self, grant_id: str) -> ScopedFolderGrant | None:
        """Retrieve grant if still active and unexpired."""
        grant = self._grants.get(grant_id)
        if grant is None or grant.is_revoked:
            return None

        if grant.expires_at and time.time() > grant.expires_at:
            # Auto-expire
            self.revoke_grant(grant_id)
            return None

        return grant
