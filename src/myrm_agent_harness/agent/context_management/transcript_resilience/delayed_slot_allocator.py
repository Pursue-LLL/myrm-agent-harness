# [INPUT]: DelayedSessionSlot, DEFAULT_MAX_CONCURRENCY_SLOTS from resilience_types
# [OUTPUT]: DelayedSlotAllocator, format_active_slot_hud
# [POS]: myrm_agent_harness.agent.context_management.transcript_resilience.delayed_slot_allocator
"""Delayed Session Slot Allocation Contract & Active Slot HUD (Item 333).

Ensures draft or idle chats consume zero concurrency quota, reserving and tracking
active execution slots strictly upon the first genuine message dispatch.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Final

from myrm_agent_harness.agent.context_management.transcript_resilience.resilience_types import (
    DEFAULT_MAX_CONCURRENCY_SLOTS,
    DelayedSessionSlot,
)


def format_active_slot_hud(
    slots: list[DelayedSessionSlot],
    total_slots_capacity: int,
) -> str:
    """Format active claimed concurrency slots into a transparent status HUD markdown block."""
    claimed_count = len([s for s in slots if s.is_claimed])
    lines: list[str] = [
        f"=== CONCURRENCY SLOTS HUD [{claimed_count}/{total_slots_capacity}] ===",
        f"Active execution capacity: {claimed_count} claimed, {total_slots_capacity - claimed_count} available.",
    ]
    if not slots:
        lines.append("No active sessions currently holding execution slots (all chats idle/draft).")
    else:
        for idx, s in enumerate(slots, 1):
            status_tag = "ACTIVE" if s.is_claimed else "UNCLAIMED"
            lines.append(
                f"[{idx}] Session: '{s.session_id}' | Holder: '{s.holder_name}' | Status: [{status_tag}] | Tokens: {s.tokens_consumed}"
            )
            if s.claimed_at_iso:
                lines.append(f"    Claimed At: {s.claimed_at_iso}")
    lines.append("==========================================")
    return "\n".join(lines)


class DelayedSlotAllocator:
    """Thread-safe manager coordinating lazy slot reservation and transparent holder HUD."""

    def __init__(self, max_concurrency_slots: int = DEFAULT_MAX_CONCURRENCY_SLOTS) -> None:
        self._lock = threading.RLock()
        self._capacity: Final[int] = max_concurrency_slots
        # session_id -> DelayedSessionSlot
        self._claimed_slots: dict[str, DelayedSessionSlot] = {}

    @property
    def capacity(self) -> int:
        """Total execution slots capacity."""
        return self._capacity

    @property
    def active_slots_count(self) -> int:
        """Number of slots currently claimed."""
        with self._lock:
            return len(self._claimed_slots)

    def claim_slot(self, session_id: str, holder_name: str) -> DelayedSessionSlot:
        """Claim a concurrency slot upon the first actual message dispatch.

        Args:
            session_id: Session identifier dispatching the execution.
            holder_name: Name of agent profile or user owning the slot.

        Returns:
            Claimed DelayedSessionSlot record.

        Raises:
            RuntimeError: If all concurrency slots are currently claimed.
        """
        with self._lock:
            if session_id in self._claimed_slots:
                # Already claimed by this session; idempotent return
                return self._claimed_slots[session_id]

            if len(self._claimed_slots) >= self._capacity:
                raise RuntimeError(
                    f"Concurrency capacity exhausted ({self._capacity}/{self._capacity} slots claimed). "
                    "Cannot allocate slot for idle/new session until an active task completes."
                )

            slot = DelayedSessionSlot(
                session_id=session_id,
                holder_name=holder_name,
                is_claimed=True,
                claimed_at_iso=datetime.now(timezone.utc).isoformat(),
                tokens_consumed=0,
            )
            self._claimed_slots[session_id] = slot
            return slot

    def record_token_usage(self, session_id: str, tokens: int) -> None:
        """Accumulate token expenditure for an active claimed slot."""
        with self._lock:
            slot = self._claimed_slots.get(session_id)
            if slot:
                self._claimed_slots[session_id] = slot.model_copy(
                    update={"tokens_consumed": slot.tokens_consumed + tokens}
                )

    def release_slot(self, session_id: str) -> bool:
        """Release a claimed slot upon session idle or completion.

        Returns:
            True if slot was claimed and is now released, False if not present.
        """
        with self._lock:
            if session_id in self._claimed_slots:
                self._claimed_slots.pop(session_id, None)
                return True
            return False

    def is_slot_claimed(self, session_id: str) -> bool:
        """Check if the given session is actively holding a slot."""
        with self._lock:
            return session_id in self._claimed_slots

    def get_active_slots(self) -> list[DelayedSessionSlot]:
        """Retrieve all currently claimed slots."""
        with self._lock:
            return list(self._claimed_slots.values())

    def get_hud_summary(self) -> str:
        """Format current active slot status into an authoritative Markdown HUD summary."""
        with self._lock:
            return format_active_slot_hud(
                slots=list(self._claimed_slots.values()),
                total_slots_capacity=self._capacity,
            )
