"""Core interceptor and emergency kill switch engine for irreversible write operations."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from .blast_radius_builder import BlastRadiusBuilder
from .contract_registry import IrreversibleWriteContractRegistry
from .types import (
    EmergencyKillResult,
    InterceptionStatus,
    IrreversibleWriteIntent,
)


class PreFlightIrreversibleWriteGuard:
    """Pre-flight interceptor and kill switch state manager for irreversible write operations."""

    def __init__(
        self,
        registry: IrreversibleWriteContractRegistry | None = None,
    ) -> None:
        self._registry = registry or IrreversibleWriteContractRegistry()
        self._lock = threading.Lock()
        self._intents: dict[str, IrreversibleWriteIntent] = {}

    @property
    def registry(self) -> IrreversibleWriteContractRegistry:
        """Access contract registry."""
        return self._registry

    def intercept(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict[str, str],
        ttl_seconds: int = 300,
    ) -> IrreversibleWriteIntent | None:
        """Intercept a tool execution before invocation if registered as an irreversible write.

        Returns:
            IrreversibleWriteIntent if intercepted and suspended for review;
            None if the tool is not an irreversible write and may proceed.
        """
        contract = self._registry.find_contract(tool_name)
        if contract is None:
            return None

        blast_radius = BlastRadiusBuilder.build_card(
            domain=contract.domain,
            arguments=arguments,
            default_risk_level=contract.default_risk_level,
            ttl_seconds=ttl_seconds,
        )

        intent = IrreversibleWriteIntent(
            intent_id=blast_radius.intent_id,
            session_id=session_id,
            tool_name=tool_name,
            domain=contract.domain,
            arguments=dict(arguments),
            blast_radius=blast_radius,
            status=InterceptionStatus.PENDING_CONFIRMATION,
        )

        with self._lock:
            self._intents[intent.intent_id] = intent

        return intent

    def approve(
        self,
        intent_id: str,
        approver: str = "user",
    ) -> IrreversibleWriteIntent:
        """Approve a suspended irreversible write intent for final dispatch.

        Raises:
            KeyError: If intent_id does not exist.
            ValueError: If intent is already resolved or expired.
        """
        with self._lock:
            intent = self._intents.get(intent_id)
            if intent is None:
                raise KeyError(f"Intent '{intent_id}' not found.")

            if intent.status != InterceptionStatus.PENDING_CONFIRMATION:
                raise ValueError(
                    f"Intent '{intent_id}' cannot be approved: current status is {intent.status}."
                )

            now = datetime.now(UTC)
            if intent.blast_radius.expires_at < now:
                timed_out = IrreversibleWriteIntent(
                    intent_id=intent.intent_id,
                    session_id=intent.session_id,
                    tool_name=intent.tool_name,
                    domain=intent.domain,
                    arguments={},
                    blast_radius=intent.blast_radius,
                    status=InterceptionStatus.TIMED_OUT,
                    resolution_reason="Blast radius review expired before user approval",
                    created_at=intent.created_at,
                )
                self._intents[intent_id] = timed_out
                raise ValueError(f"Intent '{intent_id}' expired before approval.")

            approved = IrreversibleWriteIntent(
                intent_id=intent.intent_id,
                session_id=intent.session_id,
                tool_name=intent.tool_name,
                domain=intent.domain,
                arguments=intent.arguments,
                blast_radius=intent.blast_radius,
                status=InterceptionStatus.APPROVED,
                resolution_reason=f"Approved by {approver}",
                created_at=intent.created_at,
            )
            self._intents[intent_id] = approved
            return approved

    def emergency_kill(
        self,
        intent_id: str,
        reason: str = "User aborted action via Emergency Kill Switch",
    ) -> EmergencyKillResult:
        """Emergency kill switch destroying the pending action payload and preventing side effects.

        Raises:
            KeyError: If intent_id does not exist.
        """
        with self._lock:
            intent = self._intents.get(intent_id)
            if intent is None:
                raise KeyError(f"Intent '{intent_id}' not found.")

            # Zero out arguments payload immediately to eliminate leak or accidental replay
            killed = IrreversibleWriteIntent(
                intent_id=intent.intent_id,
                session_id=intent.session_id,
                tool_name=intent.tool_name,
                domain=intent.domain,
                arguments={},
                blast_radius=intent.blast_radius,
                status=InterceptionStatus.KILLED_ABORTED,
                resolution_reason=reason,
                created_at=intent.created_at,
            )
            self._intents[intent_id] = killed

            return EmergencyKillResult(
                intent_id=intent_id,
                killed=True,
                reason=reason,
            )

    def get_intent(self, intent_id: str) -> IrreversibleWriteIntent | None:
        """Retrieve intent by ID, evaluating TTL expiration if still pending."""
        with self._lock:
            intent = self._intents.get(intent_id)
            if intent is None:
                return None

            if (
                intent.status == InterceptionStatus.PENDING_CONFIRMATION
                and intent.blast_radius.expires_at < datetime.now(UTC)
            ):
                intent = IrreversibleWriteIntent(
                    intent_id=intent.intent_id,
                    session_id=intent.session_id,
                    tool_name=intent.tool_name,
                    domain=intent.domain,
                    arguments={},
                    blast_radius=intent.blast_radius,
                    status=InterceptionStatus.TIMED_OUT,
                    resolution_reason="Blast radius review window expired",
                    created_at=intent.created_at,
                )
                self._intents[intent_id] = intent

            return intent

    def list_pending(self, session_id: str | None = None) -> list[IrreversibleWriteIntent]:
        """List all pending intents awaiting user confirmation."""
        with self._lock:
            now = datetime.now(UTC)
            results: list[IrreversibleWriteIntent] = []
            for item in self._intents.values():
                if (
                    item.status == InterceptionStatus.PENDING_CONFIRMATION
                    and item.blast_radius.expires_at >= now
                    and (session_id is None or item.session_id == session_id)
                ):
                    results.append(item)
            return results

    def cleanup_expired(self) -> int:
        """Mark all expired pending intents as timed out and return the count."""
        now = datetime.now(UTC)
        count = 0
        with self._lock:
            for iid, intent in list(self._intents.items()):
                if (
                    intent.status == InterceptionStatus.PENDING_CONFIRMATION
                    and intent.blast_radius.expires_at < now
                ):
                    self._intents[iid] = IrreversibleWriteIntent(
                        intent_id=intent.intent_id,
                        session_id=intent.session_id,
                        tool_name=intent.tool_name,
                        domain=intent.domain,
                        arguments={},
                        blast_radius=intent.blast_radius,
                        status=InterceptionStatus.TIMED_OUT,
                        resolution_reason="Cleaned up expired intent",
                        created_at=intent.created_at,
                    )
                    count += 1
        return count
