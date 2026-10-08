"""
[POS] src/myrm_agent_harness/core/security/scoped_approval/lease_engine.py
[INPUT] time, uuid, types
[OUTPUT] ScopedGrantLeaseEngine
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import time
import uuid

from .types import (
    ApprovalGrantLease,
    GrantScope,
    GrantUsageRecord,
)

logger = logging.getLogger(__name__)


class ScopedGrantLeaseEngine:
    """Manages the lifecycle, activation checking, and redemption of scoped approval leases."""

    def __init__(self) -> None:
        self._leases: dict[str, ApprovalGrantLease] = {}
        self._audit_ledger: list[GrantUsageRecord] = []

    def issue_grant(
        self,
        tool_name: str,
        scope: GrantScope,
        agent_id: str,
        session_id: str,
        task_id: str | None = None,
        current_time: float | None = None,
        ttl_seconds: float | None = None,
    ) -> ApprovalGrantLease:
        """Issue a new scoped approval grant lease."""
        now = time.time() if current_time is None else current_time
        grant_id = f"grant-{uuid.uuid4().hex[:12]}"

        expires_at: float | None = None
        if scope == GrantScope.HOURS_24:
            expires_at = now + 86400.0
        elif ttl_seconds is not None and ttl_seconds > 0:
            expires_at = now + ttl_seconds
        elif scope == GrantScope.ONCE:
            expires_at = now + 3600.0  # 1 hour expiry fallback for single-use

        lease = ApprovalGrantLease(
            grant_id=grant_id,
            tool_name=tool_name,
            scope=scope,
            agent_id=agent_id,
            session_id=session_id,
            task_id=task_id,
            granted_at=now,
            expires_at=expires_at,
            revoked=False,
            use_count=0,
        )
        self._leases[grant_id] = lease
        logger.info("Issued approval lease %s [%s] for tool '%s'", grant_id, scope, tool_name)
        return lease

    def find_active_grant(
        self,
        tool_name: str,
        agent_id: str,
        session_id: str,
        task_id: str | None = None,
        current_time: float | None = None,
    ) -> ApprovalGrantLease | None:
        """Locate an active, unexpired lease matching tool and contextual scope."""
        now = time.time() if current_time is None else current_time
        for lease in self._leases.values():
            if lease.tool_name != tool_name or lease.agent_id != agent_id:
                continue
            if lease.is_active(now, task_id, session_id):
                return lease
        return None

    def redeem_grant(
        self,
        grant_id: str,
        tool_name: str,
        agent_id: str,
        session_id: str,
        task_id: str | None = None,
        current_time: float | None = None,
    ) -> tuple[ApprovalGrantLease, GrantUsageRecord] | None:
        """Redeem a valid lease, incrementing its usage count and appending to audit ledger."""
        now = time.time() if current_time is None else current_time
        lease = self._leases.get(grant_id)
        if not lease or not lease.is_active(now, task_id, session_id):
            return None

        updated_lease = ApprovalGrantLease(
            grant_id=lease.grant_id,
            tool_name=lease.tool_name,
            scope=lease.scope,
            agent_id=lease.agent_id,
            session_id=lease.session_id,
            task_id=lease.task_id,
            granted_at=lease.granted_at,
            expires_at=lease.expires_at,
            revoked=lease.revoked,
            use_count=lease.use_count + 1,
        )
        self._leases[grant_id] = updated_lease

        record = GrantUsageRecord(
            record_id=f"rec-{uuid.uuid4().hex[:12]}",
            grant_id=grant_id,
            tool_name=tool_name,
            agent_id=agent_id,
            timestamp=now,
            task_id=task_id,
            session_id=session_id,
        )
        self._audit_ledger.append(record)
        return updated_lease, record

    def revoke_grant(self, grant_id: str) -> bool:
        """Revoke a specific approval lease by ID."""
        lease = self._leases.get(grant_id)
        if not lease or lease.revoked:
            return False

        updated_lease = ApprovalGrantLease(
            grant_id=lease.grant_id,
            tool_name=lease.tool_name,
            scope=lease.scope,
            agent_id=lease.agent_id,
            session_id=lease.session_id,
            task_id=lease.task_id,
            granted_at=lease.granted_at,
            expires_at=lease.expires_at,
            revoked=True,
            use_count=lease.use_count,
        )
        self._leases[grant_id] = updated_lease
        logger.info("Revoked approval lease: %s", grant_id)
        return True

    def revoke_all(
        self, agent_id: str | None = None, session_id: str | None = None
    ) -> int:
        """Revoke all matching active leases."""
        count = 0
        for grant_id, lease in list(self._leases.items()):
            if lease.revoked:
                continue
            if agent_id and lease.agent_id != agent_id:
                continue
            if session_id and lease.session_id != session_id:
                continue
            self.revoke_grant(grant_id)
            count += 1
        return count

    def list_active_grants(
        self, current_time: float | None = None
    ) -> tuple[ApprovalGrantLease, ...]:
        """List all currently valid, non-revoked, unexpired leases."""
        now = time.time() if current_time is None else current_time
        active: list[ApprovalGrantLease] = []
        for lease in self._leases.values():
            if (
                not lease.revoked
                and (lease.expires_at is None or now <= lease.expires_at)
                and (lease.scope != GrantScope.ONCE or lease.use_count == 0)
            ):
                active.append(lease)
        return tuple(active)

    def get_audit_ledger(self) -> tuple[GrantUsageRecord, ...]:
        """Fetch all recorded lease redemptions."""
        return tuple(self._audit_ledger)
