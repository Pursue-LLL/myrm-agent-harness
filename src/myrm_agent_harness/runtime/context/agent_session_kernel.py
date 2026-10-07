"""Unified AgentSession Kernel implementation.

Provides the single authoritative kernel governing lifecycle states,
asynchronous acknowledgment handshakes, monotonic sequence event broadcasting,
and stream event replay for client resume/reattach.
Strict 0 Any, thread-safe, single file <400 lines.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable

from .single_kernel_transport_types import (
    AsyncAckFrame,
    KernelCommandRequest,
    KernelEventFrame,
    KernelEventType,
    KernelLifecycleState,
)

logger = logging.getLogger(__name__)


class AgentSessionKernel:
    """Thread-safe core engine decoupled from transport presentation layers."""

    def __init__(
        self,
        session_id: str = "default_session",
        max_history_events: int = 1000,
    ) -> None:
        self._session_id = session_id
        self._max_history = max_history_events
        self._lock = threading.RLock()
        self._state = KernelLifecycleState.IDLE
        self._next_seq_id = 1
        self._event_history: list[KernelEventFrame] = []
        self._listeners: dict[str, Callable[[KernelEventFrame], None]] = {}
        self._active_task_id: str | None = None
        self._abort_signal = threading.Event()
        self._executor_thread: threading.Thread | None = None

    @property
    def session_id(self) -> str:
        """Return the kernel session identifier."""
        return self._session_id

    @property
    def state(self) -> KernelLifecycleState:
        """Return the current operational lifecycle state."""
        with self._lock:
            return self._state

    @property
    def active_task_id(self) -> str | None:
        """Return the active executing task identifier."""
        with self._lock:
            return self._active_task_id

    def subscribe(self, listener: Callable[[KernelEventFrame], None]) -> str:
        """Register a callback for streaming event frames, returning a subscription token."""
        with self._lock:
            token = f"sub-{uuid.uuid4().hex[:8]}"
            self._listeners[token] = listener
            return token

    def unsubscribe(self, token: str) -> bool:
        """Remove an active subscription listener."""
        with self._lock:
            return self._listeners.pop(token, None) is not None

    def emit_event(
        self,
        task_id: str,
        event_type: KernelEventType,
        payload: dict[str, str] | None = None,
    ) -> KernelEventFrame:
        """Emit a sequenced event frame to the event log and all registered listeners."""
        with self._lock:
            frame = KernelEventFrame(
                event_id=f"evt-{uuid.uuid4().hex[:10]}",
                seq_id=self._next_seq_id,
                task_id=task_id,
                event_type=event_type,
                payload=dict(payload or {}),
                timestamp_ms=int(time.time() * 1000),
            )
            self._next_seq_id += 1
            self._event_history.append(frame)

            if len(self._event_history) > self._max_history:
                self._event_history.pop(0)

            listeners_snapshot = list(self._listeners.values())

        # Notify outside lock to prevent deadlock
        for callback in listeners_snapshot:
            try:
                callback(frame)
            except Exception as exc:
                logger.warning("Error invoking kernel event listener: %s", exc)

        return frame

    def submit_prompt(
        self,
        request: KernelCommandRequest,
        *,
        custom_runner: Callable[[KernelCommandRequest, AgentSessionKernel], None] | None = None,
    ) -> AsyncAckFrame:
        """Immediately ingest and acknowledge a command before executing asynchronously.

        Guarantees sub-millisecond response handshake, completely decoupling
        network transport connections from long-running execution.
        """
        with self._lock:
            if self._state == KernelLifecycleState.DISPOSED:
                return AsyncAckFrame(
                    task_id=request.task_id,
                    accepted=False,
                    status=KernelLifecycleState.DISPOSED,
                    initial_seq_id=self._next_seq_id,
                    session_id=self._session_id,
                    message="Session kernel has been disposed.",
                )

            task_id = request.task_id
            self._active_task_id = task_id
            self._abort_signal.clear()
            self._state = KernelLifecycleState.QUEUED

            # Emit initial acceptance frame
            ack_frame = self.emit_event(
                task_id=task_id,
                event_type=KernelEventType.TASK_ACCEPTED,
                payload={"prompt_preview": request.prompt[:100], "status": "accepted"},
            )

            runner = custom_runner or self._default_run_pipeline

            # Spawn decoupled asynchronous worker
            worker = threading.Thread(
                target=self._run_task_wrapper,
                args=(request, runner),
                daemon=True,
                name=f"kernel-worker-{task_id}",
            )
            self._executor_thread = worker
            worker.start()

            return AsyncAckFrame(
                task_id=task_id,
                accepted=True,
                status=KernelLifecycleState.QUEUED,
                initial_seq_id=ack_frame.seq_id,
                session_id=self._session_id,
                message="Command queued successfully for asynchronous execution.",
            )

    def replay_events(
        self,
        last_seen_seq_id: int,
        task_id: str | None = None,
    ) -> tuple[KernelEventFrame, ...]:
        """Replay sequence frames with seq_id > last_seen_seq_id for reconnecting clients."""
        with self._lock:
            results: list[KernelEventFrame] = []
            for frame in self._event_history:
                if frame.seq_id > last_seen_seq_id and (task_id is None or frame.task_id == task_id):
                    results.append(frame)
            return tuple(results)

    def abort(self, task_id: str | None = None) -> bool:
        """Request abortion of the currently active task."""
        with self._lock:
            if self._active_task_id is None:
                return False
            if task_id is not None and task_id != self._active_task_id:
                return False

            self._abort_signal.set()
            self._state = KernelLifecycleState.ABORTING
            self.emit_event(
                task_id=self._active_task_id,
                event_type=KernelEventType.STATE_CHANGED,
                payload={"new_state": KernelLifecycleState.ABORTING.value},
            )
            return True

    def is_abort_requested(self) -> bool:
        """Check whether the active execution has received an abort signal."""
        return self._abort_signal.is_set()

    def dispose(self) -> None:
        """Clean up kernel resources, shutting down background work and listeners."""
        with self._lock:
            self.abort()
            self._state = KernelLifecycleState.DISPOSED
            self._listeners.clear()

    def _run_task_wrapper(
        self,
        request: KernelCommandRequest,
        runner: Callable[[KernelCommandRequest, AgentSessionKernel], None],
    ) -> None:
        task_id = request.task_id
        with self._lock:
            self._state = KernelLifecycleState.PROCESSING

        self.emit_event(
            task_id=task_id,
            event_type=KernelEventType.TASK_STARTED,
            payload={"status": "processing"},
        )

        try:
            runner(request, self)
            with self._lock:
                if self._abort_signal.is_set():
                    self._state = KernelLifecycleState.ABORTED
                    self.emit_event(
                        task_id=task_id,
                        event_type=KernelEventType.TASK_ABORTED,
                        payload={"reason": "Aborted by client request"},
                    )
                else:
                    self._state = KernelLifecycleState.IDLE
                    self.emit_event(
                        task_id=task_id,
                        event_type=KernelEventType.TASK_COMPLETED,
                        payload={"status": "success"},
                    )
        except Exception as exc:
            with self._lock:
                self._state = KernelLifecycleState.ERROR
            self.emit_event(
                task_id=task_id,
                event_type=KernelEventType.TASK_FAILED,
                payload={"error": str(exc)},
            )
        finally:
            with self._lock:
                if self._active_task_id == task_id:
                    self._active_task_id = None

    @staticmethod
    def _default_run_pipeline(
        request: KernelCommandRequest,
        kernel: AgentSessionKernel,
    ) -> None:
        """Default standard execution pipeline emitting thinking and text delta events."""
        task_id = request.task_id
        # Step 1: Thinking trace
        kernel.emit_event(
            task_id=task_id,
            event_type=KernelEventType.THINKING_CHUNK,
            payload={"chunk": f"Analyzing intent for prompt: {request.prompt[:50]}..."},
        )

        if kernel.is_abort_requested():
            return

        # Step 2: Text response
        kernel.emit_event(
            task_id=task_id,
            event_type=KernelEventType.TEXT_DELTA,
            payload={"delta": f"Resolved: processed '{request.prompt}'."},
        )
