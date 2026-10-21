"""Session in-flight request hard-purge manager on disposal.

Addresses the root cause benchmarked against Paseo commit 92442e74:
- In Paseo, unanswered initialize left fetchCatalog pending forever, workspace stayed loading with no timeout.
- This purger intercepts all registered in-flight pending futures.
- When dispose() is triggered, it unconditionally rejects every pending future with a SessionDisposedError.
- Completely prevents memory leaks and ensures frontend spinners terminate immediately.

[OUTPUT]
- SessionDisposePurger: Manages active requests and enforces hard reject on dispose.

[INPUT]
- __future__
- asyncio
- time

[OUTPUT]
- SessionDisposePurger

[POS]
Session in-flight request hard-purge manager on disposal.
"""

from __future__ import annotations

import asyncio
import time

from myrm_agent_harness.runtime.session_dispose.dispose_ack_types import (
    SessionDisposedError,
    SessionLifecycleState,
)


class SessionDisposePurger:
    """Coordinates lifecycle of pending asynchronous requests for a session, guaranteeing hard purge."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._state: SessionLifecycleState = SessionLifecycleState.ACTIVE
        self._pending_futures: dict[str, tuple[asyncio.Future[str], str, float]] = {}

    @property
    def state(self) -> SessionLifecycleState:
        """Current lifecycle state of the session."""
        return self._state

    @property
    def pending_count(self) -> int:
        """Number of active, unresolved requests currently pending."""
        return len(self._pending_futures)

    def register_request(
        self,
        request_id: str,
        method: str,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> asyncio.Future[str]:
        """Register a new in-flight pending request for this session.

        Raises:
            SessionDisposedError: If the session has already been disposed.
        """
        if self._state == SessionLifecycleState.DISPOSED:
            raise SessionDisposedError(
                session_id=self.session_id,
                reason="Cannot dispatch request to an already disposed session",
                purged_request_count=0,
            )

        active_loop = loop if loop is not None else asyncio.get_event_loop()
        future: asyncio.Future[str] = active_loop.create_future()
        self._pending_futures[request_id] = (future, method, time.time())
        return future

    def resolve_request(self, request_id: str, result: str) -> bool:
        """Resolve a pending request successfully with its result payload."""
        entry = self._pending_futures.pop(request_id, None)
        if entry is None:
            return False

        future, _, _ = entry
        if not future.done():
            future.set_result(result)
            return True
        return False

    def reject_request(self, request_id: str, exc: Exception) -> bool:
        """Explicitly reject a single pending request with an exception."""
        entry = self._pending_futures.pop(request_id, None)
        if entry is None:
            return False

        future, _, _ = entry
        if not future.done():
            future.set_exception(exc)
            return True
        return False

    def dispose(
        self, reason: str = "Session explicitly closed by user or system"
    ) -> int:
        """Unconditionally purge and reject all pending in-flight requests.

        This is the core anti-hang barrier: transitions session to DISPOSED and immediately
        cancels/rejects every hanging promise with SessionDisposedError so frontend loaders unblock.

        Returns:
            Count of pending requests purged and rejected.
        """
        if self._state == SessionLifecycleState.DISPOSED:
            return 0

        self._state = SessionLifecycleState.DISPOSING
        purged_count = len(self._pending_futures)
        disposed_err = SessionDisposedError(
            session_id=self.session_id,
            reason=reason,
            purged_request_count=purged_count,
        )

        # Atomically drain all pending futures
        items = list(self._pending_futures.items())
        self._pending_futures.clear()

        for _, (future, _, _) in items:
            if not future.done():
                future.set_exception(disposed_err)

        self._state = SessionLifecycleState.DISPOSED
        return purged_count
