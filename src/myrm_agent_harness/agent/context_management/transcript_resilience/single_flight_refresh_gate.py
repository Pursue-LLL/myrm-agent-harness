# [INPUT]: SingleFlightTokenState, DEFAULT_REFRESH_TIMEOUT_SECONDS from resilience_types
# [OUTPUT]: SingleFlightRefreshGate
# [POS]: myrm_agent_harness.agent.context_management.transcript_resilience.single_flight_refresh_gate
"""Single-Flight Token Refresh Mutex Gate & Transparent Replay Queue (Item 333).

Prevents concurrent 401 token refresh bursts from triggering invalid_grant disconnections
by orchestrating a single leader refresh while queuing concurrent waiters for replay.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Callable, Final

from myrm_agent_harness.agent.context_management.transcript_resilience.resilience_types import (
    DEFAULT_REFRESH_TIMEOUT_SECONDS,
    SingleFlightTokenState,
)


class SingleFlightRefreshGate:
    """Thread-safe single-flight mutex gate for high-concurrency bearer token renewals."""

    def __init__(
        self,
        initial_token: str = "",
        timeout_seconds: float = DEFAULT_REFRESH_TIMEOUT_SECONDS,
    ) -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._current_token: str = initial_token
        self._is_refreshing: bool = False
        self._timeout_seconds: Final[float] = timeout_seconds
        self._waiters_count: int = 0
        self._last_refreshed_iso: str = datetime.now(timezone.utc).isoformat()
        self._refresh_error: Exception | None = None

    @property
    def current_token(self) -> str:
        """Currently cached bearer token."""
        with self._lock:
            return self._current_token

    def get_state(self) -> SingleFlightTokenState:
        """Snapshot of current refresh gate state."""
        with self._lock:
            return SingleFlightTokenState(
                access_token=self._current_token,
                is_refreshing=self._is_refreshing,
                pending_waiters_count=self._waiters_count,
                last_refreshed_at_iso=self._last_refreshed_iso,
            )

    def execute_with_refresh(
        self,
        token_refresh_fn: Callable[[], str],
    ) -> str:
        """Coordinate token refresh, ensuring only one leader calls refresh while others wait.

        Args:
            token_refresh_fn: Callable returning newly issued access token.

        Returns:
            The authoritative active access token (either freshly acquired or broadcasted).

        Raises:
            TimeoutError: If the leader refresh exceeds configured timeout duration.
            Exception: If the leader refresh callable raises an unhandled error.
        """
        with self._condition:
            if not self._is_refreshing:
                # This caller becomes the Leader
                self._is_refreshing = True
                self._refresh_error = None
                is_leader = True
            else:
                # Another request is already refreshing; register as Waiter
                is_leader = False
                self._waiters_count += 1

        if is_leader:
            new_token = ""
            caught_exc: Exception | None = None
            try:
                new_token = token_refresh_fn()
            except Exception as e:
                caught_exc = e

            with self._condition:
                self._is_refreshing = False
                if caught_exc is not None:
                    self._refresh_error = caught_exc
                    self._condition.notify_all()
                    raise caught_exc

                self._current_token = new_token
                self._last_refreshed_iso = datetime.now(timezone.utc).isoformat()
                self._condition.notify_all()
                return new_token
        else:
            # Wait for leader to complete or timeout
            start_t = time.monotonic()
            with self._condition:
                try:
                    while self._is_refreshing:
                        elapsed = time.monotonic() - start_t
                        remaining = self._timeout_seconds - elapsed
                        if remaining <= 0:
                            raise TimeoutError(
                                f"SingleFlightRefreshGate timed out after {self._timeout_seconds}s waiting for leader."
                            )
                        self._condition.wait(timeout=remaining)

                    if self._refresh_error is not None:
                        raise self._refresh_error

                    return self._current_token
                finally:
                    self._waiters_count = max(0, self._waiters_count - 1)
