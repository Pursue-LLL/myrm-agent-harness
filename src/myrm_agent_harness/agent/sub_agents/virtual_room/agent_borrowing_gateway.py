"""Zero-credential cross-user agent capability borrowing gateway (Item 59).

[INPUT]
- Capability grant creations from model owners, delegation execution calls from teammates,
  and revocation commands.

[OUTPUT]
- Secure agent proxying without credential exfiltration, enforcing per-grant token budgets
  and instant ownership revocation.

[POS]
- Tutti-style zero-credential agent sharing mechanism for collaborative teams.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence

from myrm_agent_harness.agent.sub_agents.virtual_room.types import (
    AgentBorrowingGrant,
    BorrowingGrantStatusEnum,
)


class ZeroCredentialBorrowingGateway:
    """Brokers ephemeral Agent capability borrowing without sharing upstream credentials."""

    def __init__(self, default_grant_ttl_seconds: float = 3600.0) -> None:
        self._default_ttl = max(60.0, min(86400.0, default_grant_ttl_seconds))
        self._grants: dict[str, AgentBorrowingGrant] = {}

    def _sync_grant_status(self, grant: AgentBorrowingGrant, now: float) -> AgentBorrowingGrant:
        """Evaluates whether an active grant has transitioned to expired or exhausted."""
        if grant.status != BorrowingGrantStatusEnum.ACTIVE:
            return grant

        if grant.expires_at <= now:
            expired = AgentBorrowingGrant(
                grant_id=grant.grant_id,
                room_id=grant.room_id,
                owner_id=grant.owner_id,
                borrower_id=grant.borrower_id,
                target_agent_model=grant.target_agent_model,
                quota_tokens=grant.quota_tokens,
                used_tokens=grant.used_tokens,
                status=BorrowingGrantStatusEnum.EXPIRED,
                expires_at=grant.expires_at,
            )
            self._grants[grant.grant_id] = expired
            return expired

        if grant.used_tokens >= grant.quota_tokens:
            exhausted = AgentBorrowingGrant(
                grant_id=grant.grant_id,
                room_id=grant.room_id,
                owner_id=grant.owner_id,
                borrower_id=grant.borrower_id,
                target_agent_model=grant.target_agent_model,
                quota_tokens=grant.quota_tokens,
                used_tokens=grant.used_tokens,
                status=BorrowingGrantStatusEnum.EXHAUSTED,
                expires_at=grant.expires_at,
            )
            self._grants[grant.grant_id] = exhausted
            return exhausted

        return grant

    def create_grant(
        self,
        room_id: str,
        owner_id: str,
        borrower_id: str,
        target_agent_model: str,
        quota_tokens: int,
        ttl_seconds: float | None = None,
    ) -> AgentBorrowingGrant:
        """Issues an ephemeral zero-credential capability grant to a room collaborator."""
        if quota_tokens <= 0:
            raise ValueError(f"Quota tokens must be positive, got {quota_tokens}.")
        if owner_id == borrower_id:
            raise ValueError("Owner and borrower must be distinct participants.")

        now = time.time()
        duration = ttl_seconds if ttl_seconds is not None else self._default_ttl
        clamped_ttl = max(60.0, min(86400.0, duration))
        grant_id = f"grant-{uuid.uuid4().hex[:8]}"

        grant = AgentBorrowingGrant(
            grant_id=grant_id,
            room_id=room_id,
            owner_id=owner_id,
            borrower_id=borrower_id,
            target_agent_model=target_agent_model,
            quota_tokens=quota_tokens,
            used_tokens=0,
            status=BorrowingGrantStatusEnum.ACTIVE,
            expires_at=now + clamped_ttl,
        )
        self._grants[grant_id] = grant
        return grant

    def delegate_execution(
        self,
        grant_id: str,
        borrower_id: str,
        prompt: str,
        token_cost: int = 150,
    ) -> tuple[bool, str, int]:
        """Proxies an execution through the borrowed agent under strict token governance."""
        now = time.time()
        if grant_id not in self._grants:
            raise KeyError(f"Grant '{grant_id}' does not exist.")

        grant = self._sync_grant_status(self._grants[grant_id], now)

        if grant.borrower_id != borrower_id:
            raise PermissionError(
                f"Borrower '{borrower_id}' is not authorized to use grant '{grant_id}'."
            )

        if grant.status != BorrowingGrantStatusEnum.ACTIVE:
            raise ValueError(
                f"Grant '{grant_id}' is not active (current status: {grant.status.value})."
            )

        if grant.used_tokens + token_cost > grant.quota_tokens:
            self._sync_grant_status(
                AgentBorrowingGrant(
                    grant_id=grant.grant_id,
                    room_id=grant.room_id,
                    owner_id=grant.owner_id,
                    borrower_id=grant.borrower_id,
                    target_agent_model=grant.target_agent_model,
                    quota_tokens=grant.quota_tokens,
                    used_tokens=grant.used_tokens,
                    status=BorrowingGrantStatusEnum.EXHAUSTED,
                    expires_at=grant.expires_at,
                ),
                now,
            )
            raise ValueError(
                f"Token quota exceeded for grant '{grant_id}': requesting {token_cost} tokens "
                f"would exceed remaining budget ({grant.quota_tokens - grant.used_tokens} left)."
            )

        next_used = grant.used_tokens + token_cost
        updated_grant = AgentBorrowingGrant(
            grant_id=grant.grant_id,
            room_id=grant.room_id,
            owner_id=grant.owner_id,
            borrower_id=grant.borrower_id,
            target_agent_model=grant.target_agent_model,
            quota_tokens=grant.quota_tokens,
            used_tokens=next_used,
            status=(
                BorrowingGrantStatusEnum.EXHAUSTED
                if next_used >= grant.quota_tokens
                else BorrowingGrantStatusEnum.ACTIVE
            ),
            expires_at=grant.expires_at,
        )
        self._grants[grant_id] = updated_grant

        simulated_response = (
            f"[{grant.target_agent_model} borrowed proxy]: Processed '{prompt[:40]}...' "
            f"under zero-credential contract. ({token_cost} tokens billed)"
        )
        return True, simulated_response, next_used

    def revoke_grant(self, grant_id: str, owner_id: str) -> AgentBorrowingGrant:
        """Immediately terminates a borrowing grant by the original model owner."""
        if grant_id not in self._grants:
            raise KeyError(f"Grant '{grant_id}' not found.")

        grant = self._grants[grant_id]
        if grant.owner_id != owner_id:
            raise PermissionError(
                f"Participant '{owner_id}' is not the owner of grant '{grant_id}'."
            )

        revoked = AgentBorrowingGrant(
            grant_id=grant.grant_id,
            room_id=grant.room_id,
            owner_id=grant.owner_id,
            borrower_id=grant.borrower_id,
            target_agent_model=grant.target_agent_model,
            quota_tokens=grant.quota_tokens,
            used_tokens=grant.used_tokens,
            status=BorrowingGrantStatusEnum.REVOKED,
            expires_at=grant.expires_at,
        )
        self._grants[grant_id] = revoked
        return revoked

    def get_grant(self, grant_id: str) -> AgentBorrowingGrant:
        """Retrieves an active or historical borrowing grant."""
        if grant_id not in self._grants:
            raise KeyError(f"Grant '{grant_id}' not found.")
        return self._sync_grant_status(self._grants[grant_id], time.time())

    def list_grants(self, room_id: str | None = None) -> Sequence[AgentBorrowingGrant]:
        """Lists borrowing grants, optionally filtered by room."""
        now = time.time()
        synced = [self._sync_grant_status(g, now) for g in self._grants.values()]
        if room_id is None:
            return tuple(synced)
        return tuple(g for g in synced if g.room_id == room_id)

    def clear(self) -> None:
        """Resets all grants."""
        self._grants.clear()
