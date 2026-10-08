"""Native Credential Approval Manager.

[INPUT]
- Credential access asks, decision commands, and sequence coordinates.

[OUTPUT]
- Managed CredentialAsk states, immutable ApprovalAuditRecord logs, and verified permissions.

[POS]
- Core credential approval lifecycle manager mirroring QM #1502 security architecture.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from .link_generator import MessageLinkGenerator
from .types import (
    ApprovalAuditRecord,
    ApprovalDecision,
    CredentialAsk,
    CredentialAskStatus,
    MessageSequenceRef,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class NativeCredentialApprovalManager:
    """Manages sensitive credential requests with native approval verification and deep links."""

    def __init__(self, link_generator: MessageLinkGenerator | None = None) -> None:
        self._link_gen = link_generator or MessageLinkGenerator()
        self._asks: dict[str, CredentialAsk] = {}
        self._audit_records: list[ApprovalAuditRecord] = []

    def create_ask(
        self,
        credential_id: str,
        service_name: str,
        account_label: str,
        requester_id: str,
        owner_id: str,
        purpose: str,
        session_id: str,
        message_id: str,
        sequence_number: int,
        turn_index: int | None = None,
    ) -> CredentialAsk:
        """Create a new pending credential approval request bound to an exact message sequence."""
        if not credential_id.strip():
            raise ValueError("credential_id cannot be empty")
        if not requester_id.strip():
            raise ValueError("requester_id cannot be empty")
        if not owner_id.strip():
            raise ValueError("owner_id cannot be empty")

        msg_ref = MessageSequenceRef(
            session_id=session_id,
            message_id=message_id,
            sequence_number=sequence_number,
            turn_index=turn_index,
        )
        deep_link = self._link_gen.generate_link(
            session_id=session_id,
            message_id=message_id,
            sequence_number=sequence_number,
        )

        ask_id = f"ask-{uuid4().hex[:12]}"
        ask = CredentialAsk(
            ask_id=ask_id,
            credential_id=credential_id,
            service_name=service_name,
            account_label=account_label,
            requester_id=requester_id,
            owner_id=owner_id,
            purpose=purpose,
            message_ref=msg_ref,
            deep_link=deep_link,
            status=CredentialAskStatus.PENDING,
            created_at_iso=_now_iso(),
        )

        self._asks[ask_id] = ask
        logger.info(
            "Created native credential ask '%s' for '%s' (owner: %s, session: %s, seq: %d)",
            ask_id,
            service_name,
            owner_id,
            session_id,
            sequence_number,
        )
        return ask

    def get_ask(self, ask_id: str) -> CredentialAsk | None:
        """Retrieve credential ask by ID."""
        return self._asks.get(ask_id)

    def list_pending_asks(self, owner_id: str | None = None) -> tuple[CredentialAsk, ...]:
        """List all pending asks, optionally filtered by owner."""
        pending = [
            a for a in self._asks.values()
            if a.status == CredentialAskStatus.PENDING
            and (owner_id is None or a.owner_id == owner_id)
        ]
        return tuple(pending)

    def decide_ask(
        self,
        ask_id: str,
        decider_id: str,
        decision: ApprovalDecision,
        note: str = "",
        decided_at_iso: str | None = None,
    ) -> tuple[CredentialAsk, ApprovalAuditRecord]:
        """Record decision on a credential ask with strict authorization check."""
        ask = self._asks.get(ask_id)
        if ask is None:
            raise KeyError(f"Credential ask '{ask_id}' not found")

        # Authorization: only the designated owner can decide this request
        if ask.owner_id != decider_id:
            logger.warning(
                "Unauthorized approval attempt on ask '%s' by actor '%s' (owner: '%s')",
                ask_id,
                decider_id,
                ask.owner_id,
            )
            raise PermissionError("Only the credential owner can decide this request.")

        if ask.status != CredentialAskStatus.PENDING:
            raise ValueError(f"Cannot decide ask '{ask_id}' with status '{ask.status.value}'")

        eff_status = (
            CredentialAskStatus.APPROVED
            if decision in (ApprovalDecision.ONCE, ApprovalDecision.STANDING)
            else CredentialAskStatus.DENIED
        )
        timestamp = decided_at_iso or _now_iso()

        updated_ask = CredentialAsk(
            ask_id=ask.ask_id,
            credential_id=ask.credential_id,
            service_name=ask.service_name,
            account_label=ask.account_label,
            requester_id=ask.requester_id,
            owner_id=ask.owner_id,
            purpose=ask.purpose,
            message_ref=ask.message_ref,
            deep_link=ask.deep_link,
            status=eff_status,
            decision_mode=decision,
            decided_by=decider_id,
            decision_note=note,
            created_at_iso=ask.created_at_iso,
            decided_at_iso=timestamp,
        )
        self._asks[ask_id] = updated_ask

        audit_entry = ApprovalAuditRecord(
            audit_id=f"audit-{uuid4().hex[:12]}",
            ask_id=ask.ask_id,
            credential_id=ask.credential_id,
            service_name=ask.service_name,
            actor_id=decider_id,
            decision=decision,
            target_session_id=ask.message_ref.session_id,
            sequence_number=ask.message_ref.sequence_number,
            timestamp_iso=timestamp,
            note=note,
        )
        self._audit_records.append(audit_entry)

        logger.info(
            "Decided credential ask '%s' -> %s by actor '%s'",
            ask_id,
            decision.value,
            decider_id,
        )
        return updated_ask, audit_entry

    def get_audit_records(self) -> tuple[ApprovalAuditRecord, ...]:
        """Return all historical audit records."""
        return tuple(self._audit_records)
