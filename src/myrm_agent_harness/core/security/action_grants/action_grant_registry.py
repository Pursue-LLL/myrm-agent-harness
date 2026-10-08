"""Action Grant Registry providing four-dimensional scoped authorization."""

from __future__ import annotations

import secrets
import time

from .types import ActionGrantRecord, GrantEvaluationResult


class ActionGrantRegistry:
    """Manages scoped, time-bounded, revocable action grants bound to specific agents.

    Prevents reflexive approval fatigue while strictly maintaining agent-level isolation
    and single-direction monotonic revocation.
    """

    def __init__(self) -> None:
        self._grants: dict[str, ActionGrantRecord] = {}

    def create_grant(
        self,
        agent_id: str,
        service: str,
        action: str,
        transaction: str,
        ttl_seconds: float,
        max_uses: int | None = None,
    ) -> ActionGrantRecord:
        """Create a new 4D action grant bound to a specific agent."""
        if not agent_id or not service or not action:
            raise ValueError("agent_id, service, and action are required")

        now = time.time()
        grant_id = f"grant_{secrets.token_hex(12)}"
        record = ActionGrantRecord(
            grant_id=grant_id,
            agent_id=agent_id,
            service=service.strip().lower(),
            action=action.strip().lower(),
            transaction=transaction.strip(),
            valid_from=now,
            expires_at=now + ttl_seconds,
            max_uses=max_uses,
            used_count=0,
            is_revoked=False,
            revocation_reason=None,
            created_at=now,
        )
        self._grants[grant_id] = record
        return record

    def get_grant(self, grant_id: str) -> ActionGrantRecord | None:
        """Retrieve grant record by ID."""
        return self._grants.get(grant_id)

    def evaluate_action(
        self,
        agent_id: str,
        service: str,
        action: str,
        transaction: str,
    ) -> tuple[GrantEvaluationResult, ActionGrantRecord | None]:
        """Evaluate if an action invocation matches an active 4D grant.

        Matching criteria:
        1. agent_id matches exactly (mandatory prerequisite).
        2. service matches exactly.
        3. action matches exactly.
        4. transaction matches exactly or grant transaction is wildcard '*'.
        5. Not revoked, within [valid_from, expires_at], and within max_uses.
        """
        now = time.time()
        target_service = service.strip().lower()
        target_action = action.strip().lower()
        target_trans = transaction.strip()

        for grant in list(self._grants.values()):
            # 1. Agent prerequisite check
            if grant.agent_id != agent_id:
                continue

            # 2. Service and action dimensions
            if grant.service != target_service or grant.action != target_action:
                continue

            # 3. Transaction dimension (exact match or wildcard)
            if grant.transaction != "*" and grant.transaction != target_trans:
                continue

            # 4. Monotonic revocation check
            if grant.is_revoked:
                continue

            # 5. Time window check
            if now < grant.valid_from or now > grant.expires_at:
                continue

            # 6. Usage quota check
            if grant.max_uses is not None and grant.used_count >= grant.max_uses:
                continue

            # Matched active grant: increment usage atomically
            updated_record = ActionGrantRecord(
                grant_id=grant.grant_id,
                agent_id=grant.agent_id,
                service=grant.service,
                action=grant.action,
                transaction=grant.transaction,
                valid_from=grant.valid_from,
                expires_at=grant.expires_at,
                max_uses=grant.max_uses,
                used_count=grant.used_count + 1,
                is_revoked=grant.is_revoked,
                revocation_reason=grant.revocation_reason,
                created_at=grant.created_at,
            )
            self._grants[grant.grant_id] = updated_record
            return (
                GrantEvaluationResult(
                    is_granted=True,
                    status="granted",
                    grant_id=grant.grant_id,
                    reason="Matched active 4D action grant; auto-approved.",
                ),
                updated_record,
            )

        return (
            GrantEvaluationResult(
                is_granted=False,
                status="not_found",
                grant_id=None,
                reason="No active grant matches this action; fallback to Ask approval.",
            ),
            None,
        )

    def revoke_grant(
        self,
        grant_id: str,
        reason: str = "Explicit user revocation",
    ) -> bool:
        """Monotonically revoke a grant so it cannot be reused."""
        grant = self._grants.get(grant_id)
        if grant is None or grant.is_revoked:
            return False

        updated = ActionGrantRecord(
            grant_id=grant.grant_id,
            agent_id=grant.agent_id,
            service=grant.service,
            action=grant.action,
            transaction=grant.transaction,
            valid_from=grant.valid_from,
            expires_at=grant.expires_at,
            max_uses=grant.max_uses,
            used_count=grant.used_count,
            is_revoked=True,
            revocation_reason=reason,
            created_at=grant.created_at,
        )
        self._grants[grant_id] = updated
        return True

    def cascade_reclaim_by_service(
        self,
        service: str,
        reason: str = "Connector unlinked or credentials rotated",
    ) -> int:
        """Cascade revoke all grants associated with a given connector service."""
        target_service = service.strip().lower()
        revoked_count = 0
        for grant in list(self._grants.values()):
            if grant.service == target_service and not grant.is_revoked:
                self.revoke_grant(grant.grant_id, reason=reason)
                revoked_count += 1
        return revoked_count

    def cascade_reclaim_by_agent(
        self,
        agent_id: str,
        reason: str = "Agent session terminated",
    ) -> int:
        """Cascade revoke all grants belonging to a specific agent."""
        revoked_count = 0
        for grant in list(self._grants.values()):
            if grant.agent_id == agent_id and not grant.is_revoked:
                self.revoke_grant(grant.grant_id, reason=reason)
                revoked_count += 1
        return revoked_count

    def revoke_all(self, reason: str = "Global revocation") -> int:
        """Revoke all active grants across the entire system."""
        revoked_count = 0
        for grant in list(self._grants.values()):
            if not grant.is_revoked:
                self.revoke_grant(grant.grant_id, reason=reason)
                revoked_count += 1
        return revoked_count

    def get_active_grants(
        self,
        agent_id: str | None = None,
        service: str | None = None,
    ) -> list[ActionGrantRecord]:
        """Return list of unrevoked and unexpired grants."""
        now = time.time()
        active: list[ActionGrantRecord] = []
        for grant in self._grants.values():
            if grant.is_revoked:
                continue
            if now < grant.valid_from or now > grant.expires_at:
                continue
            if grant.max_uses is not None and grant.used_count >= grant.max_uses:
                continue
            if agent_id is not None and grant.agent_id != agent_id:
                continue
            if (
                service is not None
                and grant.service != service.strip().lower()
            ):
                continue
            active.append(grant)
        return active
