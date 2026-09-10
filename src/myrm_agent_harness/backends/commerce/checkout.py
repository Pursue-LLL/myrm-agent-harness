"""Out-of-band checkout handoff protocols, zero-model-touch payment security, and event queue.

[INPUT]
- dataclasses::dataclass, field
- enum::StrEnum
- typing::Any, Sequence
- myrm_agent_harness.backends.commerce.types::Cart
- myrm_agent_harness.backends.commerce.app_events::AppEvent, AppEventType

[OUTPUT]
- HandoffMode: Supported payment redirection modes
- CheckoutHandoff: Payment handoff descriptor supporting dual-view rendering
- enrich_checkout_payloads: Generates safe model view and rich client view
- AppEventQueue: Synchronous in-memory event queue with session isolation and idempotency
- inject_pending_app_events_into_turn: Context injector for conversational turns

[POS]
Re-exported and enhanced checkout abstraction guaranteeing PCI-DSS zero-model-touch
compliance and seamless session resumption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Sequence

from myrm_agent_harness.backends.commerce.app_events import (
    AppEvent,
    AppEventType,
)
from myrm_agent_harness.backends.commerce.types import Cart


class HandoffMode(StrEnum):
    SAME_TAB_REDIRECT = "same_tab_redirect"
    NEW_TAB_REDIRECT = "new_tab_redirect"
    POPUP_WINDOW = "popup_window"
    HOST_NATIVE_EMBED = "host_native_embed"
    QR_CODE = "qr_code"


@dataclass(frozen=True, slots=True)
class CheckoutHandoff:
    handoff_id: str
    provider: str
    payment_url: str
    mode: HandoffMode
    merchant_id: str | None = None
    expires_at_timestamp: int | None = None
    display_label: str | None = None

    def to_sanitized_model_dict(self) -> dict[str, Any]:
        """Produce safe dictionary for LLM context strictly omitting raw payment_url."""
        return {
            "handoff_id": self.handoff_id,
            "provider": self.provider,
            "mode": self.mode.value,
            "display_label": self.display_label,
            "security_fence": "PCI-DSS Protected; URL delivered securely to client.",
        }

    def to_client_payload_dict(self) -> dict[str, Any]:
        """Produce rich dictionary for frontend client rendering with real payment_url."""
        return {
            "handoff_id": self.handoff_id,
            "provider": self.provider,
            "payment_url": self.payment_url,
            "mode": self.mode.value,
            "merchant_id": self.merchant_id,
            "expires_at_timestamp": self.expires_at_timestamp,
            "display_label": self.display_label,
        }


def enrich_checkout_payloads(
    cart: Cart,
    handoffs: Sequence[CheckoutHandoff],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate pair of (model_view, client_view) ensuring zero-model-touch payment security."""
    model_view: dict[str, Any] = {
        "cart_id": cart.cart_id,
        "line_count": len(cart.lines),
        "status": "checkout_initiated",
        "handoffs": [h.to_sanitized_model_dict() for h in handoffs],
    }

    client_view: dict[str, Any] = {
        "cart_id": cart.cart_id,
        "status": "ready_for_payment",
        "handoffs": [h.to_client_payload_dict() for h in handoffs],
    }
    return model_view, client_view


class AppEventQueue:
    """Synchronous in-memory event queue with session isolation and idempotency."""

    def __init__(self) -> None:
        self._events: dict[str, list[AppEvent]] = {}
        self._seen_ids: set[str] = set()

    def enqueue(self, event: AppEvent) -> bool:
        """Enqueue an event. Returns False if event_id has already been seen."""
        if event.event_id in self._seen_ids:
            return False
        self._seen_ids.add(event.event_id)
        if event.session_id not in self._events:
            self._events[event.session_id] = []
        self._events[event.session_id].append(event)
        return True

    def has_pending(self, session_id: str) -> bool:
        """Check if session has unconsumed events."""
        events = self._events.get(session_id, [])
        return any(not e.consumed for e in events)

    def peek(self, session_id: str) -> list[AppEvent]:
        """Peek unconsumed events without marking them as consumed."""
        events = self._events.get(session_id, [])
        return [e for e in events if not e.consumed]

    def consume(self, session_id: str) -> list[AppEvent]:
        """Retrieve and mark all unconsumed events as consumed."""
        events = self._events.get(session_id, [])
        if not events:
            return []
        pending: list[AppEvent] = []
        updated: list[AppEvent] = []
        for e in events:
            if not e.consumed:
                consumed_e = AppEvent(
                    event_id=e.event_id,
                    session_id=e.session_id,
                    event_type=e.event_type,
                    payload=e.payload,
                    timestamp=e.timestamp,
                    message=getattr(e, "message", None),
                    consumed=True,
                )
                pending.append(consumed_e)
                updated.append(consumed_e)
            else:
                updated.append(e)
        self._events[session_id] = updated
        return pending

    def format_and_consume(self, session_id: str, label: str = "Host Updates") -> str | None:
        """Consume pending events and format them into an LLM turn prefix prompt block."""
        pending = self.consume(session_id)
        if not pending:
            return None
        lines = [f"[{label}: Out-of-band events occurred while waiting]"]
        for e in pending:
            msg = getattr(e, "message", None) or str(e.payload)
            lines.append(f"- {msg}")
        return "\n".join(lines)


def inject_pending_app_events_into_turn(
    queue: AppEventQueue,
    session_id: str,
    user_turn_prompt: str,
) -> str:
    """Convenience helper to prepend consumed event notifications before user turn prompt."""
    prefix = queue.format_and_consume(session_id)
    if not prefix:
        return user_turn_prompt
    return f"{prefix}\n\n{user_turn_prompt}"
