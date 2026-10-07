"""Core implementation of In-Flight Steering and Follow-Up Queue Injection Protocol Gateway.

Manages thread-safe pending steering queues, turn-boundary atomic drain pipelines,
single vs batch consumption modes, and compaction-safe secondary pickups.

[INPUT]
- agent.context_management.steering_protocol.steering_protocol_types::DrainResult, SteeredTurnContext,
  SteeringConsumptionMode, SteeringKind, SteeringMessage (POS: Type definitions for In-Flight Steering and
  Follow-Up Queue Injection Protocol.)

[OUTPUT]
- InFlightSteeringQueueGateway: Industrial gateway governing live in-flight agent steering and follow-up
  injections.

[POS]
Core implementation of In-Flight Steering and Follow-Up Queue Injection Protocol Gateway.
"""

from __future__ import annotations

import threading
import time
import uuid

from .steering_protocol_types import (
    DrainResult,
    SteeredTurnContext,
    SteeringConsumptionMode,
    SteeringKind,
    SteeringMessage,
)


class InFlightSteeringQueueGateway:
    """Industrial gateway governing live in-flight agent steering and follow-up injections."""

    STEERING_HEADER_TAG: str = "[USER STEERING / IN-FLIGHT CORRECTION]"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queues: dict[str, list[SteeringMessage]] = {}
        self._history: dict[str, list[DrainResult]] = {}

    def enqueue_steer(
        self,
        session_id: str,
        content: str,
        kind: SteeringKind = SteeringKind.STEER,
        metadata: dict[str, str] | None = None,
    ) -> SteeringMessage:
        """Enqueue an in-flight steering message without blocking agent execution."""
        clean_content = content.strip()
        if not clean_content:
            raise ValueError("Steering message content cannot be empty.")

        msg = SteeringMessage(
            message_id=f"steer-{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            kind=kind,
            content=clean_content,
            enqueued_at=time.time(),
            metadata=dict(metadata or {}),
        )

        with self._lock:
            queue = self._queues.setdefault(session_id, [])
            queue.append(msg)

        return msg

    def peek_queue(self, session_id: str) -> tuple[SteeringMessage, ...]:
        """Inspect all pending in-flight steering messages for a session."""
        with self._lock:
            return tuple(self._queues.get(session_id, []))

    def has_pending_steering(self, session_id: str) -> bool:
        """Fast check whether any steering messages are waiting in queue."""
        with self._lock:
            queue = self._queues.get(session_id)
            return bool(queue)

    def drain_steering_messages(
        self,
        session_id: str,
        mode: SteeringConsumptionMode = SteeringConsumptionMode.ALL,
        phase: str = "PRE_TURN",
    ) -> DrainResult:
        """Atomically drain pending messages at turn boundary under specified consumption mode."""
        with self._lock:
            queue = self._queues.get(session_id, [])
            if not queue:
                result = DrainResult(
                    session_id=session_id,
                    drained_messages=(),
                    injection_phase=phase,
                    timestamp=time.time(),
                )
                return result

            if mode == SteeringConsumptionMode.ONE_AT_A_TIME:
                drained = [queue.pop(0)]
            else:  # ALL
                drained = list(queue)
                queue.clear()

            result = DrainResult(
                session_id=session_id,
                drained_messages=tuple(drained),
                injection_phase=phase,
                timestamp=time.time(),
            )

            hist = self._history.setdefault(session_id, [])
            hist.append(result)

            return result

    def inject_into_messages(
        self,
        messages: list[dict[str, str]],
        drain_result: DrainResult,
    ) -> list[dict[str, str]]:
        """Inject drained steering messages into the context sequence before LLM execution."""
        if not drain_result.drained_messages:
            return list(messages)

        reconstructed = list(messages)
        for steer_msg in drain_result.drained_messages:
            kind_prefix = f"[{steer_msg.kind.value}]"
            formatted_content = (
                f"{self.STEERING_HEADER_TAG} {kind_prefix}: {steer_msg.content}"
            )
            reconstructed.append({
                "role": "user",
                "content": formatted_content,
            })

        return reconstructed

    def compaction_safe_pickup(
        self,
        session_id: str,
        current_messages: list[dict[str, str]],
        drain_result_from_phase1: DrainResult | None = None,
    ) -> tuple[list[dict[str, str]], DrainResult | None]:
        """Perform secondary poll after long-running operations (e.g. compaction) to catch live typing."""
        if not self.has_pending_steering(session_id):
            return current_messages, None

        secondary_drain = self.drain_steering_messages(
            session_id=session_id,
            mode=SteeringConsumptionMode.ALL,
            phase="POST_COMPACTION_SECONDARY",
        )

        if not secondary_drain.drained_messages:
            return current_messages, None

        injected = self.inject_into_messages(current_messages, secondary_drain)
        return injected, secondary_drain

    def clear_queue(self, session_id: str) -> int:
        """Clear all pending steering messages, returning count removed."""
        with self._lock:
            queue = self._queues.get(session_id, [])
            count = len(queue)
            if session_id in self._queues:
                self._queues[session_id].clear()
            return count

    def get_drain_history(self, session_id: str) -> tuple[DrainResult, ...]:
        """Retrieve historical drain records for audit and replay."""
        with self._lock:
            return tuple(self._history.get(session_id, []))
