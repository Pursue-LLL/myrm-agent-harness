# ============================================================================
# In-Flight Mid-Turn Steering Queue & Human Co-Steering Engine (Item 161)
# Non-blocking human directive queuing during tool execution, atomic inter-step
# context injection, and non-destructive dynamic co-steering state machine.
# ============================================================================

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Sequence

from .steering_types import (
    InFlightSteeringMessage,
    SteeringInjectionPayload,
    SteeringPriorityKind,
    SteeringQueueSnapshot,
    SteeringStatusKind,
)

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InFlightSteeringQueue:
    """Manages serialized in-flight human steering messages for a specific session."""

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._messages: dict[str, InFlightSteeringMessage] = {}
        self._pending_ids: list[str] = []
        self._total_enqueued = 0
        self._total_injected = 0
        self._total_canceled = 0

    @property
    def session_id(self) -> str:
        return self._session_id

    def enqueue_steering(
        self,
        content: str,
        priority: SteeringPriorityKind = SteeringPriorityKind.HIGH,
        author_device_id: str | None = None,
    ) -> InFlightSteeringMessage:
        """Enqueue a human steering directive without interrupting the active tool run."""
        clean_content = content.strip()
        if not clean_content:
            raise ValueError("Steering message content cannot be empty.")

        message_id = f"steer-{uuid.uuid4().hex[:12]}"
        now_iso = _utc_now_iso()

        msg = InFlightSteeringMessage(
            message_id=message_id,
            session_id=self._session_id,
            content=clean_content,
            priority=priority,
            status=SteeringStatusKind.PENDING,
            author_device_id=author_device_id,
            enqueued_at_iso=now_iso,
        )

        self._messages[message_id] = msg
        self._pending_ids.append(message_id)
        self._total_enqueued += 1

        logger.info(
            "Enqueued in-flight steering [%s] for session '%s' (priority: %s)",
            message_id,
            self._session_id,
            priority.value,
        )
        return msg

    def cancel_steering(self, message_id: str) -> bool:
        """Recall and cancel a pending steering message prior to step injection."""
        msg = self._messages.get(message_id)
        if msg is None or msg.status != SteeringStatusKind.PENDING:
            return False

        updated = InFlightSteeringMessage(
            message_id=msg.message_id,
            session_id=msg.session_id,
            content=msg.content,
            priority=msg.priority,
            status=SteeringStatusKind.CANCELED,
            author_device_id=msg.author_device_id,
            enqueued_at_iso=msg.enqueued_at_iso,
            injected_at_iso=None,
            injected_step_index=None,
        )

        self._messages[message_id] = updated
        if message_id in self._pending_ids:
            self._pending_ids.remove(message_id)
        self._total_canceled += 1

        logger.info("Canceled pending steering message '%s'", message_id)
        return True

    def get_pending_messages(self) -> tuple[InFlightSteeringMessage, ...]:
        """Get all currently pending steering messages in FIFO order."""
        return tuple(self._messages[mid] for mid in self._pending_ids if mid in self._messages)

    def consume_pending_for_step(
        self,
        step_index: int,
    ) -> SteeringInjectionPayload | None:
        """Atomically consume pending steering messages upon micro-step completion.

        Synthesizes an `<in_flight_human_steering>` block for the subsequent LLM turn.
        Returns None if no pending directives exist (0 extra tokens, 0 context pollution).
        """
        if not self._pending_ids:
            return None

        now_iso = _utc_now_iso()
        consumed_ids: list[str] = list(self._pending_ids)
        self._pending_ids.clear()

        consumed_messages: list[InFlightSteeringMessage] = []
        for mid in consumed_ids:
            msg = self._messages.get(mid)
            if msg is not None and msg.status == SteeringStatusKind.PENDING:
                injected = InFlightSteeringMessage(
                    message_id=msg.message_id,
                    session_id=msg.session_id,
                    content=msg.content,
                    priority=msg.priority,
                    status=SteeringStatusKind.INJECTED,
                    author_device_id=msg.author_device_id,
                    enqueued_at_iso=msg.enqueued_at_iso,
                    injected_at_iso=now_iso,
                    injected_step_index=step_index,
                )
                self._messages[mid] = injected
                consumed_messages.append(injected)
                self._total_injected += 1

        if not consumed_messages:
            return None

        # Build prompt injection block
        lines: list[str] = [
            '<in_flight_human_steering priority="HIGH">',
            "[实时人机共驾纠偏指令 (由用户在当前微步骤执行期间排队注入)]:",
        ]
        for idx, m in enumerate(consumed_messages, start=1):
            lines.append(f"{idx}. [{m.priority.value.upper()}] {m.content}")

        lines.extend([
            "重要指导要求: 请在接下来的规划与工具调用中优先遵循上述最新纠偏指令，顺畅修正航向，无需中断流程。",
            "</in_flight_human_steering>",
        ])

        injected_block = "\n".join(lines)
        return SteeringInjectionPayload(
            injected_block=injected_block,
            injected_message_ids=tuple(m.message_id for m in consumed_messages),
            count=len(consumed_messages),
        )

    def get_snapshot(self) -> SteeringQueueSnapshot:
        """Return comprehensive status metrics snapshot of steering queue."""
        pending = self.get_pending_messages()
        return SteeringQueueSnapshot(
            session_id=self._session_id,
            pending_messages=pending,
            total_enqueued=self._total_enqueued,
            total_injected=self._total_injected,
            total_canceled=self._total_canceled,
        )


class CoSteeringSessionManager:
    """Multi-session coordinator for in-flight human co-steering queues."""

    def __init__(self) -> None:
        self._queues: dict[str, InFlightSteeringQueue] = {}

    def get_or_create_queue(self, session_id: str) -> InFlightSteeringQueue:
        """Retrieve existing steering queue or instantiate a new one."""
        queue = self._queues.get(session_id)
        if queue is None:
            queue = InFlightSteeringQueue(session_id=session_id)
            self._queues[session_id] = queue
        return queue

    def enqueue(
        self,
        session_id: str,
        content: str,
        priority: SteeringPriorityKind = SteeringPriorityKind.HIGH,
        author_device_id: str | None = None,
    ) -> InFlightSteeringMessage:
        """Enqueue human steering directive into session queue."""
        return self.get_or_create_queue(session_id).enqueue_steering(
            content=content,
            priority=priority,
            author_device_id=author_device_id,
        )

    def cancel(self, session_id: str, message_id: str) -> bool:
        """Cancel a pending directive in session queue."""
        queue = self._queues.get(session_id)
        return queue.cancel_steering(message_id) if queue is not None else False

    def consume_for_step(
        self,
        session_id: str,
        step_index: int,
    ) -> SteeringInjectionPayload | None:
        """Consume pending directives for next micro-step in session."""
        queue = self._queues.get(session_id)
        return queue.consume_pending_for_step(step_index) if queue is not None else None

    def get_snapshot(self, session_id: str) -> SteeringQueueSnapshot | None:
        """Get snapshot of session steering queue or None if absent."""
        queue = self._queues.get(session_id)
        return queue.get_snapshot() if queue is not None else None
