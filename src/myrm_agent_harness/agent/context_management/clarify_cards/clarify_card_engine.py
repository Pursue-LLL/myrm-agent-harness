# [INPUT]: ClarifyCardPayload, ClarifyCardStatus, ClarifyDispatchReceipt
# [OUTPUT]: ClarifyCardEngine
# [POS]: agent/context_management/clarify_cards/clarify_card_engine.py

"""Clarification cards lifecycle state machine and registry engine.

[INPUT]
- ClarifyCardPayload: Immutable record of a clarification question card.
- ClarifyCardStatus: Lifecycle status enumeration.
- ClarifyDispatchReceipt: Attestation receipt confirming status transition.

[OUTPUT]
- ClarifyCardEngine: Engine coordinating card rendering, answering, expiration, and connection invalidation.

[POS]
State machine and storage registry for interactive clarification cards.
"""

from __future__ import annotations

from dataclasses import replace
import time
import uuid

from .clarify_card_types import (
    ClarifyCardPayload,
    ClarifyCardStatus,
    ClarifyDispatchReceipt,
)


class ClarifyCardEngine:
    """State machine and registry managing rendering, answering, expiration, and invalidation."""

    def __init__(self) -> None:
        # Keyed by request_id
        self._cards: dict[str, ClarifyCardPayload] = {}
        # Keyed by session_id -> list of request_ids
        self._session_card_index: dict[str, list[str]] = {}

    def render_clarify_card(self, card: ClarifyCardPayload) -> ClarifyDispatchReceipt:
        """Register a new clarification card and auto-expire any existing pending card in the same session."""
        session_id = card.session_id

        # 1. Check if there is an existing pending card for the same session; expire it to prevent stack deadlock
        existing_pending = self.get_active_pending_card(session_id)
        if existing_pending is not None and existing_pending.request_id != card.request_id:
            self.expire_clarify_card(existing_pending.request_id, reason="superseded_by_new_card")

        # 2. Store new card
        self._cards[card.request_id] = card
        self._session_card_index.setdefault(session_id, []).append(card.request_id)

        # 3. Issue render receipt
        receipt_id = f"rcpt_rend_{uuid.uuid4().hex[:10]}"
        return ClarifyDispatchReceipt.create(
            receipt_id=receipt_id,
            request_id=card.request_id,
            session_id=session_id,
            action="render",
            status=card.status,
            card=card,
        )

    def answer_clarify_card(
        self,
        request_id: str,
        answer: str,
        *,
        session_id: str,
        connection_id: str,
    ) -> tuple[ClarifyCardPayload, ClarifyDispatchReceipt]:
        """Answer a pending clarification card with strict session and connection validation."""
        card = self._cards.get(request_id)
        if card is None:
            raise KeyError(f"Clarify card with request_id '{request_id}' not found")

        # Session and connection validation
        if card.session_id != session_id:
            raise ValueError(
                f"Session ID mismatch: card belongs to '{card.session_id}', got '{session_id}'"
            )
        if card.connection_id != connection_id:
            raise ValueError(
                f"Connection ID mismatch: card bound to '{card.connection_id}', got '{connection_id}'"
            )

        # Check timeout
        if card.is_timed_out:
            self.expire_clarify_card(request_id, reason="timeout_on_answering")
            raise TimeoutError(f"Clarify card '{request_id}' has expired and cannot be answered")

        # Check status
        if card.status != ClarifyCardStatus.PENDING:
            raise ValueError(
                f"Cannot answer clarify card in status '{card.status.value}', expected 'pending'"
            )

        # Validate answer if options exist and custom input is disabled
        clean_answer = answer.strip()
        if card.options and not card.allow_custom_input:
            valid_values = {opt.value for opt in card.options}
            valid_labels = {opt.label for opt in card.options}
            if clean_answer not in valid_values and clean_answer not in valid_labels:
                raise ValueError(
                    f"Answer '{clean_answer}' is not a valid choice for closed options"
                )

        now = time.time()
        updated = replace(
            card,
            status=ClarifyCardStatus.ANSWERED,
            user_answer=clean_answer,
            resolved_at=now,
        )
        self._cards[request_id] = updated

        receipt_id = f"rcpt_answ_{uuid.uuid4().hex[:10]}"
        receipt = ClarifyDispatchReceipt.create(
            receipt_id=receipt_id,
            request_id=request_id,
            session_id=session_id,
            action="answer",
            status=ClarifyCardStatus.ANSWERED,
            card=updated,
        )
        return updated, receipt

    def expire_clarify_card(
        self,
        request_id: str,
        reason: str = "timeout",
    ) -> tuple[ClarifyCardPayload, ClarifyDispatchReceipt]:
        """Expire a pending clarification card, forbidding further user response."""
        card = self._cards.get(request_id)
        if card is None:
            raise KeyError(f"Clarify card with request_id '{request_id}' not found")

        if card.status != ClarifyCardStatus.PENDING:
            # Idempotently return existing non-pending card
            receipt = ClarifyDispatchReceipt.create(
                receipt_id=f"rcpt_exp_{uuid.uuid4().hex[:10]}",
                request_id=request_id,
                session_id=card.session_id,
                action="expire_noop",
                status=card.status,
                card=card,
            )
            return card, receipt

        now = time.time()
        updated = replace(
            card,
            status=ClarifyCardStatus.EXPIRED,
            resolved_at=now,
            metadata={**card.metadata, "expire_reason": reason},
        )
        self._cards[request_id] = updated

        receipt = ClarifyDispatchReceipt.create(
            receipt_id=f"rcpt_exp_{uuid.uuid4().hex[:10]}",
            request_id=request_id,
            session_id=card.session_id,
            action="expire",
            status=ClarifyCardStatus.EXPIRED,
            card=updated,
        )
        return updated, receipt

    def invalidate_on_connection_change(
        self,
        session_id: str,
        *,
        old_connection_id: str | None = None,
    ) -> tuple[ClarifyCardPayload, ...]:
        """Invalidate all pending clarify cards on connection reset to prevent stale cross-connection answering."""
        request_ids = self._session_card_index.get(session_id, [])
        invalidated: list[ClarifyCardPayload] = []

        now = time.time()
        for req_id in request_ids:
            card = self._cards.get(req_id)
            if card is not None and card.status == ClarifyCardStatus.PENDING:
                if old_connection_id is None or card.connection_id == old_connection_id:
                    updated = replace(
                        card,
                        status=ClarifyCardStatus.INVALIDATED,
                        resolved_at=now,
                        metadata={**card.metadata, "invalidated_reason": "connection_change"},
                    )
                    self._cards[req_id] = updated
                    invalidated.append(updated)

        return tuple(invalidated)

    def get_active_pending_card(self, session_id: str) -> ClarifyCardPayload | None:
        """Retrieve the currently active pending clarify card for a session, checking for timeout."""
        request_ids = self._session_card_index.get(session_id, [])
        for req_id in reversed(request_ids):
            card = self._cards.get(req_id)
            if card is not None and card.status == ClarifyCardStatus.PENDING:
                if card.is_timed_out:
                    self.expire_clarify_card(req_id, reason="auto_timeout_check")
                    continue
                return card
        return None

    def get_card(self, request_id: str) -> ClarifyCardPayload | None:
        """Fetch a clarify card by its request_id."""
        return self._cards.get(request_id)
