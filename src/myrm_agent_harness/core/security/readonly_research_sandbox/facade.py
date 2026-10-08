"""
[POS] src/myrm_agent_harness/core/security/readonly_research_sandbox/facade.py
[INPUT] threading, typing, .ephemeral_cow_overlay, .readonly_lease_manager, .types
[OUTPUT] ReadOnlyResearchSandboxFacade

Unified Facade for Read-Only Autonomous Research Lease & Immutable Snapshot Sandbox Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import threading

from .ephemeral_cow_overlay import EphemeralCowOverlay
from .readonly_lease_manager import ReadOnlyLeaseManager
from .types import (
    EphemeralCowFileRecord,
    LeaseStatusEnum,
    ReadOnlyLeaseRecord,
    ReadOnlyResearchMetrics,
    ReadOnlyShieldBadge,
    ResearchModeEnum,
    WorkspaceSnapshot,
)


class ReadOnlyResearchSandboxFacade:
    """Coordinates read-only lease contracts, in-memory CoW overlays, purity verification, and badges."""

    def __init__(self, default_ttl_seconds: float = 3600.0) -> None:
        self._lock = threading.RLock()
        self._lease_manager = ReadOnlyLeaseManager(default_ttl_seconds=default_ttl_seconds)
        self._cow_overlay = EphemeralCowOverlay()
        self._metrics = ReadOnlyResearchMetrics()

    def grant_research_lease(
        self,
        session_id: str,
        research_mode: ResearchModeEnum = ResearchModeEnum.AUTONOMOUS_RESEARCH,
        ttl_seconds: float | None = None,
        custom_allowed_tools: tuple[str, ...] | None = None,
    ) -> ReadOnlyLeaseRecord:
        """Grant dynamic read-only research lease to session."""
        lease = self._lease_manager.grant_lease(
            session_id=session_id,
            research_mode=research_mode,
            ttl_seconds=ttl_seconds,
            custom_allowed_tools=custom_allowed_tools,
        )
        with self._lock:
            self._metrics.total_leases_granted += 1
            self._metrics.active_leases_count += 1
        return lease

    def get_lease(self, session_id: str) -> ReadOnlyLeaseRecord | None:
        """Retrieve lease for session."""
        return self._lease_manager.get_lease(session_id)

    def revoke_lease(self, session_id: str) -> ReadOnlyLeaseRecord | None:
        """Revoke active read-only lease."""
        lease = self._lease_manager.revoke_lease(session_id)
        if lease is not None and lease.status == LeaseStatusEnum.REVOKED:
            with self._lock:
                self._metrics.leases_revoked_count += 1
                if self._metrics.active_leases_count > 0:
                    self._metrics.active_leases_count -= 1
        return lease

    def evaluate_tool(self, session_id: str, tool_name: str) -> tuple[bool, str]:
        """Evaluate if tool can run or is physically blocked by read-only lease."""
        allowed, reason = self._lease_manager.evaluate_tool(session_id, tool_name)
        if not allowed:
            with self._lock:
                self._metrics.write_attempts_blocked += 1
        return allowed, reason

    def take_snapshot(
        self, session_id: str, baseline_files: dict[str, str | bytes]
    ) -> WorkspaceSnapshot:
        """Capture immutable cryptographic baseline snapshot of protected workspace."""
        return self._cow_overlay.take_snapshot(session_id, baseline_files)

    def get_snapshot(self, session_id: str) -> WorkspaceSnapshot | None:
        """Retrieve baseline snapshot."""
        return self._cow_overlay.get_snapshot(session_id)

    def write_ephemeral_output(
        self, session_id: str, virtual_path: str, content: str | bytes
    ) -> EphemeralCowFileRecord:
        """Write intermediate research output strictly into in-memory CoW overlay."""
        rec = self._cow_overlay.write_ephemeral_file(session_id, virtual_path, content)
        with self._lock:
            self._metrics.ephemeral_cow_files_staged += 1
        return rec

    def read_ephemeral_output(self, session_id: str, virtual_path: str) -> bytes | None:
        """Read intermediate file from CoW overlay."""
        return self._cow_overlay.read_ephemeral_file(session_id, virtual_path)

    def list_ephemeral_outputs(self, session_id: str) -> list[EphemeralCowFileRecord]:
        """List all transient files created in session's CoW overlay."""
        return self._cow_overlay.list_ephemeral_files(session_id)

    def purge_ephemeral_overlay(self, session_id: str) -> int:
        """Purge and destroy in-memory CoW overlay on research task completion."""
        purged = self._cow_overlay.purge_overlay(session_id)
        with self._lock:
            self._metrics.overlays_purged_count += 1
        return purged

    def verify_workspace_purity(
        self, session_id: str, current_files: dict[str, str | bytes]
    ) -> tuple[bool, str]:
        """Verify that current workspace matches baseline snapshot without pollution."""
        is_pure, explanation = self._cow_overlay.verify_workspace_purity(session_id, current_files)
        with self._lock:
            self._metrics.purity_verifications_count += 1
        return is_pure, explanation

    def get_shield_badge(
        self, session_id: str, current_files: dict[str, str | bytes] | None = None
    ) -> ReadOnlyShieldBadge:
        """Construct real-time UI security indicator badge."""
        lease = self._lease_manager.get_lease(session_id)
        is_active = lease is not None and lease.status == LeaseStatusEnum.ACTIVE
        mode = lease.research_mode if lease else ResearchModeEnum.GENERAL_INTERACTIVE
        lease_id = lease.lease_id if lease else None

        overlay_files = self._cow_overlay.list_ephemeral_files(session_id)
        cow_active = len(overlay_files) > 0

        purity_verified = True
        if current_files is not None:
            purity_verified, _ = self._cow_overlay.verify_workspace_purity(session_id, current_files)

        label = (
            "🛡️ Active Read-Only Research Mode (Side-effects Physically Stripped)"
            if is_active
            else "General Interactive Mode"
        )

        return ReadOnlyShieldBadge(
            is_read_only_active=is_active,
            active_lease_id=lease_id,
            research_mode=mode,
            cow_overlay_active=cow_active,
            workspace_purity_verified=purity_verified,
            badge_label=label,
        )

    def get_metrics(self) -> ReadOnlyResearchMetrics:
        """Retrieve operational telemetry snapshot."""
        with self._lock:
            return ReadOnlyResearchMetrics(
                total_leases_granted=self._metrics.total_leases_granted,
                active_leases_count=self._metrics.active_leases_count,
                leases_revoked_count=self._metrics.leases_revoked_count,
                write_attempts_blocked=self._metrics.write_attempts_blocked,
                ephemeral_cow_files_staged=self._metrics.ephemeral_cow_files_staged,
                overlays_purged_count=self._metrics.overlays_purged_count,
                purity_verifications_count=self._metrics.purity_verifications_count,
            )


_GLOBAL_READONLY_RESEARCH_FACADE: ReadOnlyResearchSandboxFacade | None = None
_GLOBAL_LOCK = threading.Lock()


def get_readonly_research_sandbox_facade() -> ReadOnlyResearchSandboxFacade:
    """Get the process-wide ReadOnlyResearchSandboxFacade singleton instance."""
    global _GLOBAL_READONLY_RESEARCH_FACADE
    if _GLOBAL_READONLY_RESEARCH_FACADE is None:
        with _GLOBAL_LOCK:
            if _GLOBAL_READONLY_RESEARCH_FACADE is None:
                _GLOBAL_READONLY_RESEARCH_FACADE = ReadOnlyResearchSandboxFacade()
    return _GLOBAL_READONLY_RESEARCH_FACADE

