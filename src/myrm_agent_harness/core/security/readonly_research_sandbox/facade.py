"""
[POS] src/myrm_agent_harness/core/security/readonly_research_sandbox/facade.py
[INPUT] threading, typing, .readonly_lease_manager, .types
[OUTPUT] ReadOnlyResearchSandboxFacade, get_readonly_research_sandbox_facade

Unified Facade for the Read-Only Autonomous Research Lease: grants, revokes and enforces leases, and counts them.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import threading

from .readonly_lease_manager import ReadOnlyLeaseManager
from .types import (
    LeaseStatusEnum,
    ReadOnlyLeaseRecord,
    ReadOnlyResearchMetrics,
    ResearchModeEnum,
)


class ReadOnlyResearchSandboxFacade:
    """Coordinates read-only lease contracts and their telemetry."""

    def __init__(self, default_ttl_seconds: float = 3600.0) -> None:
        self._lock = threading.RLock()
        self._lease_manager = ReadOnlyLeaseManager(default_ttl_seconds=default_ttl_seconds)
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

    def get_metrics(self) -> ReadOnlyResearchMetrics:
        """Retrieve operational telemetry snapshot."""
        with self._lock:
            return ReadOnlyResearchMetrics(
                total_leases_granted=self._metrics.total_leases_granted,
                active_leases_count=self._metrics.active_leases_count,
                leases_revoked_count=self._metrics.leases_revoked_count,
                write_attempts_blocked=self._metrics.write_attempts_blocked,
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
