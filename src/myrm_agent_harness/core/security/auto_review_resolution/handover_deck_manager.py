"""
[POS] src/myrm_agent_harness/core/security/auto_review_resolution/handover_deck_manager.py
[INPUT] threading, time, uuid, typing, .types (HandoverDeckPayload, HandoverStatusEnum)
[OUTPUT] HandoverDeckManager

Pre-stages contextual commands and actions into native human handover cards,
enabling operators to review parameters and click-to-execute without deadlocks.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import threading
import time
import uuid

from .types import HandoverDeckPayload, HandoverStatusEnum


class HandoverDeckManager:
    """Manages pre-staged interactive human handover decks."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._decks: dict[str, HandoverDeckPayload] = {}

    def stage_handover(
        self,
        session_id: str,
        task_description: str,
        prepared_command: str,
        parameters: dict[str, str],
        guidance_notes: str,
    ) -> HandoverDeckPayload:
        """Stage an interactive human handover card."""
        hid = f"deck-{uuid.uuid4().hex[:12]}"
        now = time.time()
        deck = HandoverDeckPayload(
            handover_id=hid,
            session_id=session_id,
            task_description=task_description,
            prepared_command=prepared_command,
            parameters=parameters.copy(),
            guidance_notes=guidance_notes,
            created_at=now,
            status=HandoverStatusEnum.STAGED,
        )
        with self._lock:
            self._decks[hid] = deck
        return deck

    def get_handover(self, handover_id: str) -> HandoverDeckPayload | None:
        """Retrieve handover deck descriptor."""
        with self._lock:
            return self._decks.get(handover_id)

    def list_staged_handovers(self, session_id: str | None = None) -> list[HandoverDeckPayload]:
        """List currently staged handover cards."""
        with self._lock:
            results = [d for d in self._decks.values() if d.status == HandoverStatusEnum.STAGED]
            if session_id is not None:
                results = [d for d in results if d.session_id == session_id]
            return results

    def execute_handover(self, handover_id: str) -> HandoverDeckPayload | None:
        """Mark handover card as executed by user."""
        now = time.time()
        with self._lock:
            deck = self._decks.get(handover_id)
            if deck is None or deck.status != HandoverStatusEnum.STAGED:
                return deck

            updated = HandoverDeckPayload(
                handover_id=deck.handover_id,
                session_id=deck.session_id,
                task_description=deck.task_description,
                prepared_command=deck.prepared_command,
                parameters=deck.parameters,
                guidance_notes=deck.guidance_notes,
                created_at=deck.created_at,
                status=HandoverStatusEnum.EXECUTED_BY_USER,
                executed_at=now,
            )
            self._decks[handover_id] = updated
            return updated

    def dismiss_handover(self, handover_id: str) -> HandoverDeckPayload | None:
        """Mark handover card as dismissed by user."""
        with self._lock:
            deck = self._decks.get(handover_id)
            if deck is None or deck.status != HandoverStatusEnum.STAGED:
                return deck

            updated = HandoverDeckPayload(
                handover_id=deck.handover_id,
                session_id=deck.session_id,
                task_description=deck.task_description,
                prepared_command=deck.prepared_command,
                parameters=deck.parameters,
                guidance_notes=deck.guidance_notes,
                created_at=deck.created_at,
                status=HandoverStatusEnum.DISMISSED_BY_USER,
            )
            self._decks[handover_id] = updated
            return updated
