"""Thread-safe session-scoped wakeup budget tracker.

Guards against runaway autonomous self-wakes by bounding consecutive wakes
until an explicit human turn resets the budget.

[INPUT]
- threading
- datetime
- types

[OUTPUT]
- WakeupBudgetTracker

[POS]
Thread-safe session-scoped wakeup budget tracker.
"""

import threading
from datetime import UTC, datetime

from .types import WakeupBudgetState


class WakeupBudgetTracker:
    """Tracks and enforces bounded consecutive wakes per session."""

    def __init__(self, default_max_consecutive_wakes: int = 3) -> None:
        self._default_max_consecutive_wakes: int = max(1, default_max_consecutive_wakes)
        self._states: dict[str, WakeupBudgetState] = {}
        self._lock: threading.Lock = threading.Lock()

    def get_budget_state(self, session_id: str) -> WakeupBudgetState:
        """Retrieve a copy of current budget state for the session."""
        with self._lock:
            if session_id not in self._states:
                self._states[session_id] = WakeupBudgetState(
                    max_consecutive_wakes=self._default_max_consecutive_wakes
                )
            state = self._states[session_id]
            return WakeupBudgetState(
                consecutive_wakes=state.consecutive_wakes,
                max_consecutive_wakes=state.max_consecutive_wakes,
                last_wake_time=state.last_wake_time,
                last_human_reset_time=state.last_human_reset_time,
                is_user_stopped=state.is_user_stopped,
            )

    def record_human_turn(self, session_id: str) -> WakeupBudgetState:
        """Reset consecutive wake count when a verified human user message is received."""
        with self._lock:
            state = self._states.get(session_id)
            now = datetime.now(tz=UTC)
            if state is None:
                state = WakeupBudgetState(
                    consecutive_wakes=0,
                    max_consecutive_wakes=self._default_max_consecutive_wakes,
                    last_human_reset_time=now,
                    is_user_stopped=False,
                )
                self._states[session_id] = state
            else:
                state.consecutive_wakes = 0
                state.is_user_stopped = False
                state.last_human_reset_time = now

            return WakeupBudgetState(
                consecutive_wakes=state.consecutive_wakes,
                max_consecutive_wakes=state.max_consecutive_wakes,
                last_wake_time=state.last_wake_time,
                last_human_reset_time=state.last_human_reset_time,
                is_user_stopped=state.is_user_stopped,
            )

    def record_user_stop(self, session_id: str) -> None:
        """Flag the session as stopped by human user, suppressing subsequent background wakes."""
        with self._lock:
            state = self._states.get(session_id)
            if state is None:
                state = WakeupBudgetState(
                    consecutive_wakes=0,
                    max_consecutive_wakes=self._default_max_consecutive_wakes,
                    is_user_stopped=True,
                )
                self._states[session_id] = state
            else:
                state.is_user_stopped = True

    def consume_wake_budget(self, session_id: str) -> bool:
        """Attempt to consume 1 autonomous wake budget.

        Returns True if budget was available and consumed, False if exhausted.
        """
        with self._lock:
            state = self._states.get(session_id)
            if state is None:
                state = WakeupBudgetState(
                    consecutive_wakes=0,
                    max_consecutive_wakes=self._default_max_consecutive_wakes,
                )
                self._states[session_id] = state

            if state.is_user_stopped:
                return False

            if state.consecutive_wakes >= state.max_consecutive_wakes:
                return False

            state.consecutive_wakes += 1
            state.last_wake_time = datetime.now(tz=UTC)
            return True

    def reset_session(self, session_id: str) -> None:
        """Completely clear session state from memory (e.g. on session teardown)."""
        with self._lock:
            self._states.pop(session_id, None)
