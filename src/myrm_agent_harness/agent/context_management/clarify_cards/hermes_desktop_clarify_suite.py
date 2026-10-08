"""Comprehensive facade suite for Hermes Desktop clarification cards.

[INPUT]
- ClarifyCardPayload: Data model for clarification questions.
- ClarifyCardStatus: Lifecycle status enum.
- ClarifyDispatchReceipt: Receipt for lifecycle events.
- ClarifyOptionItem: Discrete selectable choice.
- ClarifyResponsePath: UI delivery channel.

[OUTPUT]
- HermesDesktopClarifyCardsSuite: Unified facade managing rendering, answering, expiration, and input interception.
- create_clarify_card: Convenience builder creating ClarifyCardPayload.

[POS]
End-to-end facade suite for interactive clarify card lifecycles.
"""

from __future__ import annotations

import time
from typing import Mapping, Sequence
import uuid

from .clarify_card_engine import ClarifyCardEngine
from .clarify_card_types import (
    ClarifyCardPayload,
    ClarifyCardStatus,
    ClarifyDispatchReceipt,
    ClarifyOptionItem,
    ClarifyResponsePath,
)


def create_clarify_card(
    question: str,
    *,
    session_id: str,
    connection_id: str,
    request_id: str | None = None,
    options: Sequence[ClarifyOptionItem] = (),
    allow_custom_input: bool = True,
    timeout_seconds: float = 300.0,
    response_path: ClarifyResponsePath = ClarifyResponsePath.DASHBOARD,
    metadata: Mapping[str, str | int | float | bool | None] | None = None,
) -> ClarifyCardPayload:
    """Convenience builder creating a strongly typed ClarifyCardPayload."""
    req_id = request_id if request_id is not None else f"clarify_{uuid.uuid4().hex[:12]}"
    return ClarifyCardPayload(
        request_id=req_id,
        session_id=session_id,
        connection_id=connection_id,
        question=question,
        options=tuple(options),
        allow_custom_input=allow_custom_input,
        timeout_seconds=timeout_seconds,
        response_path=response_path,
        status=ClarifyCardStatus.PENDING,
        user_answer=None,
        created_at=time.time(),
        resolved_at=None,
        metadata=dict(metadata) if metadata else {},
    )


class HermesDesktopClarifyCardsSuite:
    """Unified facade suite for clarification card rendering, answering, expiration, and user input interception."""

    def __init__(self) -> None:
        self._engine = ClarifyCardEngine()

    def render_clarification(
        self,
        question: str,
        *,
        session_id: str,
        connection_id: str,
        request_id: str | None = None,
        options: Sequence[ClarifyOptionItem] = (),
        allow_custom_input: bool = True,
        timeout_seconds: float = 300.0,
        response_path: ClarifyResponsePath = ClarifyResponsePath.DASHBOARD,
        metadata: Mapping[str, str | int | float | bool | None] | None = None,
    ) -> tuple[ClarifyCardPayload, ClarifyDispatchReceipt]:
        """Render and register a clarification card, expiring any stale pending cards in the session."""
        card = create_clarify_card(
            question=question,
            session_id=session_id,
            connection_id=connection_id,
            request_id=request_id,
            options=options,
            allow_custom_input=allow_custom_input,
            timeout_seconds=timeout_seconds,
            response_path=response_path,
            metadata=metadata,
        )
        receipt = self._engine.render_clarify_card(card)
        return card, receipt

    def answer_clarification(
        self,
        request_id: str,
        answer: str,
        *,
        session_id: str,
        connection_id: str,
    ) -> tuple[ClarifyCardPayload, ClarifyDispatchReceipt]:
        """Answer an active clarification question with validation."""
        return self._engine.answer_clarify_card(
            request_id=request_id,
            answer=answer,
            session_id=session_id,
            connection_id=connection_id,
        )

    def expire_clarification(
        self,
        request_id: str,
        reason: str = "timeout",
    ) -> tuple[ClarifyCardPayload, ClarifyDispatchReceipt]:
        """Expire a clarification card, preventing subsequent answers."""
        return self._engine.expire_clarify_card(request_id, reason=reason)

    def invalidate_connection(
        self,
        session_id: str,
        *,
        old_connection_id: str | None = None,
    ) -> tuple[ClarifyCardPayload, ...]:
        """Invalidate pending clarification cards upon connection switch or reset."""
        return self._engine.invalidate_on_connection_change(
            session_id=session_id,
            old_connection_id=old_connection_id,
        )

    def intercept_user_input(
        self,
        text: str,
        *,
        session_id: str,
        connection_id: str,
    ) -> tuple[bool, ClarifyCardPayload | None, ClarifyDispatchReceipt | None]:
        """Intercept user chat text; if an active pending clarify card exists, answer it first."""
        pending_card = self._engine.get_active_pending_card(session_id)
        if pending_card is None:
            return False, None, None

        if pending_card.connection_id != connection_id:
            # Stale connection - invalidate rather than answering wrongly
            self._engine.invalidate_on_connection_change(session_id, old_connection_id=pending_card.connection_id)
            return False, None, None

        try:
            answered_card, receipt = self._engine.answer_clarify_card(
                request_id=pending_card.request_id,
                answer=text,
                session_id=session_id,
                connection_id=connection_id,
            )
            return True, answered_card, receipt
        except (ValueError, TimeoutError):
            return False, None, None

    def get_active_card(self, session_id: str) -> ClarifyCardPayload | None:
        """Get the current active pending card for a session, checking for timeout."""
        return self._engine.get_active_pending_card(session_id)

    def get_card(self, request_id: str) -> ClarifyCardPayload | None:
        """Fetch card by request_id."""
        return self._engine.get_card(request_id)
