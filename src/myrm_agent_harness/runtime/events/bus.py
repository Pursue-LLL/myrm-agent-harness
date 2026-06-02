"""Event Bus Implementation

A lightweight, purely asyncio-based in-memory event bus for the Harness framework.
Designed to decouple side-effects (like memory persistence, logging) from the main
execution path of the Agent, ensuring extremely low Time-To-First-Token (TTFT).

Features:
- Strongly typed events (inherit from BaseEvent)
- Non-blocking publishing
- Graceful shutdown support
- Zero external dependencies

[INPUT]
- (none)

[OUTPUT]
- BaseEvent: Base class for all events in the Harness framework.
- EventBus: Publish-subscribe event bus with session-level filtering.
- get_event_bus: Get the default global event bus instance.

[POS]
Event Bus Implementation
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)


class BaseEvent:
    """Base class for all events in the Harness framework."""

    pass


E = TypeVar("E", bound=BaseEvent)
EventHandler = Callable[[E], Awaitable[None]]


class EventBus:
    """
    Lightweight Async Event Bus.

    Manages subscriptions and asynchronous event dispatching.
    """

    def __init__(self) -> None:
        self._subscribers: dict[type[BaseEvent], list[EventHandler[Any]]] = defaultdict(list)
        self._tasks: set[asyncio.Task[Any]] = set()
        self._running: bool = False

    def start(self) -> None:
        """Start accepting events."""
        self._running = True
        logger.debug("EventBus started.")

    async def stop(self, timeout: float = 5.0) -> None:
        """
        Gracefully stop the event bus.
        Waits for all pending event handler tasks to complete.
        """
        self._running = False
        logger.debug(f"EventBus stopping. Waiting for {len(self._tasks)} pending tasks...")

        if self._tasks:
            _done, pending = await asyncio.wait(self._tasks, timeout=timeout, return_when=asyncio.ALL_COMPLETED)
            if pending:
                logger.warning(f"EventBus stopped with {len(pending)} tasks still pending after {timeout}s timeout.")
                for task in pending:
                    task.cancel()
            else:
                logger.debug("All EventBus tasks completed successfully.")

        self._tasks.clear()
        logger.debug("EventBus stopped.")

    def subscribe(self, event_type: type[E], handler: EventHandler[E]) -> None:
        """
        Subscribe an async handler to a specific event type.
        """
        self._subscribers[event_type].append(handler)
        logger.debug(f"Subscribed handler {handler.__name__} to event {event_type.__name__}")

    def publish(self, event: BaseEvent) -> None:
        """
        Publish an event non-blockingly.

        This method returns immediately. The handlers are scheduled as asyncio Tasks.
        If the bus is stopped, the event is ignored with a warning.
        """
        if not self._running:
            logger.warning(f"EventBus is stopped. Ignoring event: {type(event).__name__}")
            return

        event_type = type(event)
        handlers = self._subscribers.get(event_type, [])

        if not handlers:
            logger.debug(f"No subscribers for event: {event_type.__name__}")
            return

        for handler in handlers:
            # Create a task for each handler to ensure they run concurrently and don't block
            task = asyncio.create_task(self._safe_execute(handler, event))
            self._tasks.add(task)
            # Remove task from the set when it's done to prevent memory leaks
            task.add_done_callback(self._tasks.discard)

    async def _safe_execute(self, handler: EventHandler[Any], event: BaseEvent) -> None:
        """Execute a handler and catch any exceptions to prevent task crashes."""
        try:
            await handler(event)
        except Exception as e:
            logger.error(
                f"Error executing event handler {handler.__name__} for event {type(event).__name__}: {e}", exc_info=True
            )


# Global default instance for convenience within the framework
_default_bus = EventBus()


def get_event_bus() -> EventBus:
    """Get the default global event bus instance."""
    return _default_bus
