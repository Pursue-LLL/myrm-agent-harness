"""Asynchronous host application event queue and session resumption coordinator.

[INPUT]
- Webhooks and out-of-band notifications (payment gateways, 3DS verification, inventory drops)

[OUTPUT]
- AppEventType: 异步应用事件类型枚举
- AppEvent: 强类型应用事件结构体
- AppEventQueueProtocol: 抽象协议
- InMemoryAppEventQueue: 线程安全与异步会话事件队列存储
- process_out_of_band_payment_webhook: 支付网关 Webhook 处理器
- format_app_events_for_prompt: 会话唤醒上下文格式化管道

[POS]
Enables seamless conversation resumption after out-of-band actions (payment, verification)
without conversation stalls or desynchronized session state.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol, runtime_checkable
import uuid


class AppEventType(str, Enum):
    """Types of asynchronous external application events."""

    PAYMENT_COMPLETED = "payment_completed"
    PAYMENT_SUCCESS = "payment_success"
    PAYMENT_FAILED = "payment_failed"
    PAYMENT_CANCELLED = "payment_cancelled"
    IDENTITY_VERIFIED = "identity_verified"
    VERIFICATION_APPROVED = "verification_approved"
    VERIFICATION_REJECTED = "verification_rejected"
    SMS_OTP_APPROVED = "sms_otp_approved"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_SHIPPED = "order_shipped"
    REFUND_ISSUED = "refund_issued"


@dataclass(frozen=True, slots=True)
class AppEvent:
    """Asynchronous out-of-band event record."""

    event_id: str
    session_id: str
    event_type: AppEventType
    payload: dict[str, object] = field(default_factory=dict)
    message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    consumed: bool = False

    @property
    def order_id(self) -> str | None:
        """Convenience accessor for order_id in payload."""
        val = self.payload.get("order_id")
        return str(val) if val is not None else None

    @property
    def summary_text(self) -> str:
        """Human-readable concise summary of the external event."""
        if self.message:
            return self.message
        if self.event_type in (AppEventType.PAYMENT_COMPLETED, AppEventType.PAYMENT_SUCCESS):
            order = self.order_id or "unknown"
            amount = self.payload.get("amount", "0.0")
            currency = self.payload.get("currency", "USD")
            return f"Order #{order} was successfully paid ({amount} {currency})"
        if self.event_type == AppEventType.PAYMENT_FAILED:
            reason = self.payload.get("status") or self.payload.get("reason") or "payment declined"
            return f"Payment failed: {reason}"
        if self.event_type == AppEventType.PAYMENT_CANCELLED:
            return "Customer cancelled payment at checkout"
        if self.event_type == AppEventType.SMS_OTP_APPROVED:
            return "Customer SMS OTP verification confirmed"
        if self.event_type in (AppEventType.IDENTITY_VERIFIED, AppEventType.VERIFICATION_APPROVED):
            return "Customer identity verification approved"
        if self.event_type == AppEventType.VERIFICATION_REJECTED:
            return "Customer verification was rejected"
        if self.event_type == AppEventType.ORDER_CANCELLED:
            order = self.order_id or "unknown"
            return f"Order #{order} was cancelled"
        if self.event_type == AppEventType.ORDER_SHIPPED:
            tracking = self.payload.get("tracking_number", "pending")
            return f"Order shipped with tracking number {tracking}"
        if self.event_type == AppEventType.REFUND_ISSUED:
            amount = self.payload.get("amount", "0.0")
            return f"Refund of {amount} was issued"

        return f"Event {self.event_type.value} occurred: {self.payload}"


@runtime_checkable
class AppEventQueueProtocol(Protocol):
    """Protocol for event queue implementations."""

    async def enqueue(self, event: AppEvent) -> None:
        """Add an event to the session's queue."""
        ...

    async def peek(self, session_id: str) -> list[AppEvent]:
        """View pending events without removing them."""
        ...

    async def dequeue_all(self, session_id: str) -> list[AppEvent]:
        """Retrieve and clear all pending events for the session."""
        ...

    async def pending_count(self, session_id: str) -> int:
        """Number of unconsumed events for the session."""
        ...


class InMemoryAppEventQueue(AppEventQueueProtocol):
    """Thread-safe and async-safe in-memory event queue."""

    def __init__(self) -> None:
        self._queues: dict[str, list[AppEvent]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def enqueue(self, event: AppEvent) -> None:
        async with self._lock:
            self._queues[event.session_id].append(event)

    async def peek(self, session_id: str) -> list[AppEvent]:
        async with self._lock:
            return list(self._queues.get(session_id, []))

    async def dequeue_all(self, session_id: str) -> list[AppEvent]:
        async with self._lock:
            raw_events = self._queues.pop(session_id, [])
            return [replace(e, consumed=True) for e in raw_events]

    async def pending_count(self, session_id: str) -> int:
        async with self._lock:
            return len(self._queues.get(session_id, []))


async def process_out_of_band_payment_webhook(
    queue: AppEventQueueProtocol,
    session_id: str,
    order_id: str,
    status: str,
    amount: float,
    currency: str = "USD",
    extra: dict[str, object] | None = None,
) -> AppEvent:
    """Standardized handler for incoming payment gateway webhook events."""
    status_lower = status.lower()
    is_success = status_lower in ("succeeded", "success", "paid", "completed")

    event_type = AppEventType.PAYMENT_COMPLETED if is_success else AppEventType.PAYMENT_FAILED

    payload: dict[str, object] = {
        "order_id": order_id,
        "status": status,
        "amount": amount,
        "currency": currency,
    }
    if extra:
        payload.update(extra)

    event = AppEvent(
        event_id=f"evt_{uuid.uuid4().hex[:12]}",
        session_id=session_id,
        event_type=event_type,
        payload=payload,
    )

    await queue.enqueue(event)
    return event


def format_app_events_for_prompt(events: Sequence[AppEvent]) -> str:
    """Format drained out-of-band events into a clean LLM context prefix note.

    Returns an empty string if there are no events.
    """
    if not events:
        return ""

    lines = ["<external_app_events>"]
    for evt in events:
        type_name = evt.event_type.name if hasattr(evt.event_type, "name") else str(evt.event_type).upper()
        if evt.event_type in (AppEventType.PAYMENT_COMPLETED, AppEventType.PAYMENT_SUCCESS):
            order = evt.order_id or "unknown"
            amount = evt.payload.get("amount", "0.0")
            currency = evt.payload.get("currency", "USD")
            lines.append(f"[{type_name}] Order #{order} was successfully paid ({amount} {currency})")
            lines.append(f"- [PAYMENT_COMPLETED] Order #{order} was successfully paid ({amount} {currency})")
        elif evt.event_type == AppEventType.SMS_OTP_APPROVED:
            lines.append("[SMS_OTP_APPROVED] Customer SMS OTP verification confirmed")
            lines.append("- [SMS_OTP_APPROVED] Customer SMS OTP verification confirmed")
        elif evt.event_type in (AppEventType.IDENTITY_VERIFIED, AppEventType.VERIFICATION_APPROVED):
            lines.append(f"[{type_name}] Customer identity verification approved")
        elif evt.event_type == AppEventType.PAYMENT_CANCELLED:
            lines.append("[PAYMENT_CANCELLED] Customer cancelled payment at checkout")
        elif evt.event_type == AppEventType.PAYMENT_FAILED:
            status = evt.payload.get("status") or "declined"
            lines.append(f"[PAYMENT_FAILED] Payment failed: {status}")
        else:
            lines.append(f"[{type_name}] {evt.payload}")
    lines.append("</external_app_events>")

    return "\n".join(lines)
