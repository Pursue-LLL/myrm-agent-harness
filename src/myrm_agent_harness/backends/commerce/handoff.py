"""Out-of-band checkout handoff and asynchronous app event queue.

[INPUT]
- .types::Cart (POS: 购物车 DTO)

[OUTPUT]
- HandoffMode: 场外结账手交跳转模式枚举
- CheckoutHandoff: 零模型接触结账手交实体（包含支付链接与模型脱敏视图）
- AppEventType: 宿主外部应用事件类型枚举
- AppEvent: 结构化宿主应用事件数据结构
- AppEventQueue: 线程安全会话外部事件队列管理器
- enrich_checkout_payloads: 零模型接触支付手交拆分函数（分别产出模型脱敏视图与客户端渲染视图）

[POS]
Provides enterprise PCI-DSS compliant checkout handoff separation and asynchronous
host-level AppEvent injection for session resumption after out-of-band payments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.backends.commerce.types import Cart


class HandoffMode(StrEnum):
    """Execution mode for out-of-band checkout handoff."""

    SAME_TAB_REDIRECT = "same_tab_redirect"
    POPUP_WINDOW = "popup_window"
    HOST_NATIVE_EMBED = "host_native_embed"


@dataclass(frozen=True, slots=True)
class CheckoutHandoff:
    """Out-of-band checkout destination details."""

    handoff_id: str
    provider: str
    payment_url: str
    mode: HandoffMode = HandoffMode.SAME_TAB_REDIRECT
    merchant_id: str | None = None
    expires_at_timestamp: int | None = None
    display_label: str = "Proceed to Secure Payment"

    def to_sanitized_model_dict(self) -> dict[str, str]:
        """Produce a sanitized representation strictly hiding raw payment_url from model context."""
        return {
            "handoff_id": self.handoff_id,
            "provider": self.provider,
            "mode": self.mode.value,
            "display_label": self.display_label,
            "security_fence": "PCI-DSS Protected: Payment URL withheld from model context",
        }

    def to_client_payload_dict(self) -> dict[str, object]:
        """Produce full payload for frontend client renderer containing executable payment_url."""
        payload: dict[str, object] = {
            "handoff_id": self.handoff_id,
            "provider": self.provider,
            "payment_url": self.payment_url,
            "mode": self.mode.value,
            "display_label": self.display_label,
        }
        if self.merchant_id is not None:
            payload["merchant_id"] = self.merchant_id
        if self.expires_at_timestamp is not None:
            payload["expires_at_timestamp"] = self.expires_at_timestamp
        return payload


class AppEventType(StrEnum):
    """Types of asynchronous events generated outside conversation turns."""

    PAYMENT_COMPLETED = "payment_completed"
    PAYMENT_CANCELLED = "payment_cancelled"
    PAYMENT_FAILED = "payment_failed"
    VERIFICATION_APPROVED = "verification_approved"
    VERIFICATION_REJECTED = "verification_rejected"
    CART_UPDATED_OUT_OF_BAND = "cart_updated_out_of_band"
    CUSTOM_APP_EVENT = "custom_app_event"


@dataclass(frozen=True, slots=True)
class AppEvent:
    """Structured out-of-band application event queued on host session."""

    event_id: str
    event_type: AppEventType
    session_id: str
    message: str | None = None
    payload: dict[str, object] = field(default_factory=dict)
    created_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def format_for_transcript(self) -> str:
        """Format event as structured prefix message for next agent turn."""
        return f"[Host Event: {self.message}]"


class AppEventQueue:
    """Thread-safe queue manager for asynchronous session-scoped host application events."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events_by_session: dict[str, list[AppEvent]] = {}
        self._seen_event_ids: set[str] = set()

    def enqueue(self, event: AppEvent) -> bool:
        """Enqueue an event if not already processed (idempotent). Returns True if enqueued."""
        with self._lock:
            if event.event_id in self._seen_event_ids:
                return False
            self._seen_event_ids.add(event.event_id)
            if event.session_id not in self._events_by_session:
                self._events_by_session[event.session_id] = []
            self._events_by_session[event.session_id].append(event)
            return True

    def peek(self, session_id: str) -> list[AppEvent]:
        """Inspect pending events without consuming them."""
        with self._lock:
            return list(self._events_by_session.get(session_id, []))

    def has_pending(self, session_id: str) -> bool:
        """Check whether there are unconsumed events for this session."""
        with self._lock:
            events = self._events_by_session.get(session_id)
            return bool(events)

    def consume(self, session_id: str) -> list[AppEvent]:
        """Atomically drain all pending events for the session."""
        with self._lock:
            events = self._events_by_session.pop(session_id, [])
            return events

    def format_and_consume(
        self, session_id: str, *, label: str = "Host Events since your last reply"
    ) -> str | None:
        """Atomically consume events and format them into conversational context prefix."""
        events = self.consume(session_id)
        if not events:
            return None
        joined_messages = " ".join(e.message for e in events)
        return f"[{label}: {joined_messages}]"

    def clear(self) -> None:
        """Clear all session queues and deduplication sets."""
        with self._lock:
            self._events_by_session.clear()
            self._seen_event_ids.clear()


def enrich_checkout_payloads(
    cart: Cart,
    handoffs: list[CheckoutHandoff],
) -> tuple[dict[str, object], dict[str, object]]:
    """Split checkout artifacts into model-safe context and client rendering payload.

    Returns:
        (model_view, client_view)
        - model_view: Sanitized for LLM context, contains cart summary but NO payment URLs.
        - client_view: Enriched with executable payment URLs and handoff routing for WebUI.
    """
    base_summary: dict[str, object] = {
        "cart_id": cart.cart_id,
        "line_count": len(cart.lines),
        "total_quantity": cart.total_quantity,
        "subtotal": cart.subtotal,
        "currency": cart.currency,
    }

    model_view: dict[str, object] = {
        **base_summary,
        "handoffs": [h.to_sanitized_model_dict() for h in handoffs],
        "status": "checkout_initiated",
    }

    client_view: dict[str, object] = {
        **base_summary,
        "handoffs": [h.to_client_payload_dict() for h in handoffs],
        "status": "ready_for_payment",
    }

    return model_view, client_view
