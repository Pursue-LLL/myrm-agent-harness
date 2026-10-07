"""[POS]: myrm_agent_harness/toolkits/memory/dialectic_guard/state_machine.py
[INPUT]: DialecticLivenessConfig and runtime session signals.
[OUTPUT]: Robust state machine managing thread timeout recovery, orphan rejection, stale pivot discard, and exponential backoff.
"""

from __future__ import annotations

import hashlib
import time
from uuid import uuid4

from myrm_agent_harness.toolkits.memory.dialectic_guard.models import (
    DialecticExecutionSlot,
    DialecticLivenessAuditLog,
    DialecticLivenessConfig,
    DialecticPendingResult,
    ExecutionSlotState,
    LivenessTelemetry,
)


class DialecticLivenessStateMachine:
    """State machine governing background dialectic inference liveness and lifecycle."""

    def __init__(self, config: DialecticLivenessConfig | None = None) -> None:
        self._config = config or DialecticLivenessConfig()
        self._slots: dict[str, DialecticExecutionSlot] = {}
        self._pending: dict[str, DialecticPendingResult] = {}
        self._empty_streaks: dict[str, int] = {}
        self._last_fired_turn: dict[str, int] = {}
        self._counters: dict[str, dict[str, int]] = {}
        self._audit_logs: dict[str, list[DialecticLivenessAuditLog]] = {}

    @property
    def config(self) -> DialecticLivenessConfig:
        return self._config

    def _ensure_session(self, session_id: str) -> None:
        if session_id not in self._counters:
            self._counters[session_id] = {
                "total_fires": 0,
                "dead_threads_recovered": 0,
                "stale_pivots_discarded": 0,
                "stale_tokens_rejected": 0,
                "successful_consumptions": 0,
            }
        if session_id not in self._audit_logs:
            self._audit_logs[session_id] = []

    def _record_audit(
        self,
        session_id: str,
        action: str,
        turn: int,
        detail: str,
        now_mono: float,
    ) -> None:
        self._ensure_session(session_id)
        entry = DialecticLivenessAuditLog(
            event_id=f"audit_{uuid4().hex[:12]}",
            session_id=session_id,
            action=action,
            turn=turn,
            detail=detail,
            timestamp_monotonic=now_mono,
        )
        self._audit_logs[session_id].append(entry)

    def get_effective_cadence(self, session_id: str) -> int:
        """Compute dynamic cadence adapting to empty inference streaks."""
        streak = self._empty_streaks.get(session_id, 0)
        multiplier = min(1 + streak, self._config.max_backoff_multiplier)
        return self._config.base_cadence * multiplier

    def is_slot_dead(self, session_id: str, now_mono: float | None = None) -> bool:
        """Probe if running slot exceeded timeout threshold and mark dead if hung."""
        self._ensure_session(session_id)
        slot = self._slots.get(session_id)
        if slot is None or slot.status != ExecutionSlotState.RUNNING:
            return False

        now = now_mono if now_mono is not None else time.monotonic()
        elapsed = now - slot.start_monotonic
        stale_limit = slot.timeout_seconds * self._config.stale_thread_multiplier

        if elapsed > stale_limit:
            slot.status = ExecutionSlotState.DEAD
            self._counters[session_id]["dead_threads_recovered"] += 1
            self._record_audit(
                session_id=session_id,
                action="thread_timeout_dead",
                turn=slot.fired_turn,
                detail=f"Slot timed out (elapsed={elapsed:.2f}s > threshold={stale_limit:.2f}s)",
                now_mono=now,
            )
            return True

        return False

    def should_trigger(
        self,
        session_id: str,
        current_turn: int,
        now_mono: float | None = None,
    ) -> tuple[bool, int | None]:
        """Determine whether dialectic inference should trigger and allocate a cycle token."""
        self._ensure_session(session_id)
        now = now_mono if now_mono is not None else time.monotonic()

        # 1. Sweep hung threads first
        self.is_slot_dead(session_id, now_mono=now)

        slot = self._slots.get(session_id)
        if slot is not None and slot.status == ExecutionSlotState.RUNNING:
            return False, None

        # 2. Check cadence turn requirements
        effective_cadence = self.get_effective_cadence(session_id)
        last_turn = self._last_fired_turn.get(session_id, -effective_cadence)
        if current_turn - last_turn < effective_cadence:
            return False, None

        # 3. Allocate next generation cycle token
        next_token = (slot.cycle_token if slot else 0) + 1
        new_slot = DialecticExecutionSlot(
            session_id=session_id,
            cycle_token=next_token,
            start_monotonic=now,
            fired_turn=current_turn,
            status=ExecutionSlotState.RUNNING,
            timeout_seconds=self._config.timeout_seconds,
        )
        self._slots[session_id] = new_slot
        self._last_fired_turn[session_id] = current_turn
        self._counters[session_id]["total_fires"] += 1

        self._record_audit(
            session_id=session_id,
            action="cycle_triggered",
            turn=current_turn,
            detail=f"Allocated cycle_token={next_token} with effective_cadence={effective_cadence}",
            now_mono=now,
        )
        return True, next_token

    def submit_result(
        self,
        session_id: str,
        cycle_token: int,
        content: str | None,
        now_mono: float | None = None,
    ) -> bool:
        """Submit background inference result, guarding against orphan zombie returns."""
        self._ensure_session(session_id)
        now = now_mono if now_mono is not None else time.monotonic()
        slot = self._slots.get(session_id)

        # Orphan rejection guard: Token generation must match active cycle token
        if slot is None or slot.cycle_token != cycle_token:
            self._counters[session_id]["stale_tokens_rejected"] += 1
            self._record_audit(
                session_id=session_id,
                action="orphan_stale_token_rejected",
                turn=slot.fired_turn if slot else -1,
                detail=f"Late result with token={cycle_token} rejected (active={slot.cycle_token if slot else None})",
                now_mono=now,
            )
            return False

        slot.status = ExecutionSlotState.COMPLETED
        cleaned = content.strip() if content else ""

        if not cleaned:
            # Empty streak backoff progression
            current_streak = self._empty_streaks.get(session_id, 0) + 1
            self._empty_streaks[session_id] = current_streak
            slot.status = ExecutionSlotState.IDLE
            self._record_audit(
                session_id=session_id,
                action="empty_outcome_backoff_stepped",
                turn=slot.fired_turn,
                detail=f"Empty dialectic result stepped streak to {current_streak}",
                now_mono=now,
            )
            return True

        # Valid non-empty dialectic result staged pending consumption
        fp = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
        self._pending[session_id] = DialecticPendingResult(
            session_id=session_id,
            cycle_token=cycle_token,
            fired_turn=slot.fired_turn,
            fired_monotonic=now,
            content=cleaned,
            fingerprint=fp,
        )
        slot.status = ExecutionSlotState.IDLE
        self._record_audit(
            session_id=session_id,
            action="result_staged_pending",
            turn=slot.fired_turn,
            detail=f"Staged pending dialectic result (fp={fp[:8]})",
            now_mono=now,
        )
        return True

    def consume_pending_result(self, session_id: str, current_turn: int) -> str | None:
        """Consume pending inference result or discard it if conversational pivot occurred."""
        self._ensure_session(session_id)
        pending = self._pending.get(session_id)
        if pending is None:
            return None

        stale_turn_limit = (
            self._config.base_cadence * self._config.stale_result_multiplier
        )
        delta_turns = current_turn - pending.fired_turn

        if delta_turns > stale_turn_limit:
            # Conversational pivot invalidation guard
            del self._pending[session_id]
            self._counters[session_id]["stale_pivots_discarded"] += 1
            self._record_audit(
                session_id=session_id,
                action="stale_pivot_discarded",
                turn=current_turn,
                detail=f"Discarded result fired at turn={pending.fired_turn} (delta={delta_turns} > limit={stale_turn_limit})",
                now_mono=time.monotonic(),
            )
            return None

        # Valid consumption
        del self._pending[session_id]
        self._counters[session_id]["successful_consumptions"] += 1
        self._empty_streaks[session_id] = 0
        self._record_audit(
            session_id=session_id,
            action="result_consumed_successfully",
            turn=current_turn,
            detail=f"Consumed dialectic result fired at turn={pending.fired_turn}",
            now_mono=time.monotonic(),
        )
        return pending.content

    def notify_critical_mutation(self, session_id: str, reason: str = "") -> None:
        """External wakeup channel: reset backoff streak on authoritative event."""
        self._ensure_session(session_id)
        old_streak = self._empty_streaks.get(session_id, 0)
        self._empty_streaks[session_id] = 0
        self._record_audit(
            session_id=session_id,
            action="mutation_wakeup_streak_reset",
            turn=self._last_fired_turn.get(session_id, 0),
            detail=f"Reset backoff streak from {old_streak} to 0: {reason or 'critical event'}",
            now_mono=time.monotonic(),
        )

    def get_telemetry(self, session_id: str, current_turn: int) -> LivenessTelemetry:
        """Produce comprehensive liveness and backoff telemetry snapshot."""
        self._ensure_session(session_id)
        slot = self._slots.get(session_id)
        counters = self._counters[session_id]
        return LivenessTelemetry(
            session_id=session_id,
            current_turn=current_turn,
            effective_cadence=self.get_effective_cadence(session_id),
            empty_streak=self._empty_streaks.get(session_id, 0),
            slot_state=slot.status.value if slot else ExecutionSlotState.IDLE.value,
            active_cycle_token=slot.cycle_token if slot else 0,
            total_fires=counters["total_fires"],
            dead_threads_recovered=counters["dead_threads_recovered"],
            stale_pivots_discarded=counters["stale_pivots_discarded"],
            stale_tokens_rejected=counters["stale_tokens_rejected"],
            successful_consumptions=counters["successful_consumptions"],
            audit_events=tuple(self._audit_logs.get(session_id, [])),
        )

    def get_audit_logs(self, session_id: str) -> list[DialecticLivenessAuditLog]:
        """Return full audit log history for session."""
        self._ensure_session(session_id)
        return list(self._audit_logs.get(session_id, []))
