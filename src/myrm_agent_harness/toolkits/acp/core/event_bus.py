"""Unified event bus for the ACP runtime system.

Provides publish-subscribe decoupling between event producers (RuntimeBackend
implementations) and consumers (UI, logging, monitoring). Supports session-level
filtering and async callbacks.


[INPUT]
- myrm_agent_harness.toolkits.acp.types::RuntimeEvent, RuntimeEventType (POS: ACP runtime type definitions)

[OUTPUT]
- EventBus: publish-subscribe event bus with session-level filtering and async callbacks

[POS]
ACP event bus layer. Provides decoupled event dispatch mechanism for the Runtime system with session
isolation and type filtering.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine

from myrm_agent_harness.toolkits.acp.types import RuntimeEvent, RuntimeEventType

logger = logging.getLogger(__name__)

SyncCallback = Callable[[RuntimeEvent], None]
AsyncCallback = Callable[[RuntimeEvent], Coroutine[object, object, None]]
EventCallback = SyncCallback | AsyncCallback

_SubscriptionId = int


class EventBus:
    """Publish-subscribe event bus with session-level filtering.

    Usage::

        bus = EventBus()

        # Subscribe to all events
        sub_id = bus.subscribe(callback=my_handler)

        # Subscribe to specific event type for a specific session
        sub_id = bus.subscribe(
            event_type=RuntimeEventType.ERROR,
            callback=error_handler,
            session_id="session-123",
        )

        # Emit an event
        await bus.emit(event)

        # Unsubscribe
        bus.unsubscribe(sub_id)
    """

    def __init__(self) -> None:
        self._subscriptions: dict[_SubscriptionId, _Subscription] = {}
        self._next_id: _SubscriptionId = 0

    def subscribe(
        self,
        callback: EventCallback,
        *,
        event_type: RuntimeEventType | None = None,
        session_id: str | None = None,
    ) -> _SubscriptionId:
        """Register a callback for events.

        Args:
            callback: Sync or async callable receiving a RuntimeEvent.
            event_type: If set, only events of this type trigger the callback.
            session_id: If set, only events for this session trigger the callback.

        Returns:
            A subscription ID for later unsubscription.
        """
        sub_id = self._next_id
        self._next_id += 1
        self._subscriptions[sub_id] = _Subscription(
            callback=callback,
            event_type=event_type,
            session_id=session_id,
        )
        return sub_id

    def unsubscribe(self, subscription_id: _SubscriptionId) -> None:
        """Remove a subscription by ID. No-op if already removed."""
        self._subscriptions.pop(subscription_id, None)

    async def emit(self, event: RuntimeEvent) -> None:
        """Dispatch an event to all matching subscribers.

        Exceptions in callbacks are logged but do not propagate.
        """
        for sub in self._subscriptions.values():
            if not sub.matches(event):
                continue
            try:
                result = sub.callback(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.warning(
                    "event_bus_callback_error event_type=%s session=%s",
                    event.type,
                    event.session_id,
                    exc_info=True,
                )

    def clear(self) -> None:
        """Remove all subscriptions."""
        self._subscriptions.clear()


class _Subscription:
    """Internal subscription record with optional type/session filters."""

    __slots__ = ("callback", "event_type", "session_id")

    def __init__(
        self,
        callback: EventCallback,
        event_type: RuntimeEventType | None,
        session_id: str | None,
    ) -> None:
        self.callback = callback
        self.event_type = event_type
        self.session_id = session_id

    def matches(self, event: RuntimeEvent) -> bool:
        if self.event_type is not None and event.type != self.event_type:
            return False
        return not (self.session_id is not None and event.session_id != self.session_id)
