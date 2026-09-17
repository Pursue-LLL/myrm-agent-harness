"""In-process bus and registry for cognitive clock events and handlers.

[INPUT]
- .cadence::CognitiveCadence, CognitiveClockTaskSpec, CognitiveClockTickEvent
- .signals::CooperativePauseSignal, get_global_pause_signal

[OUTPUT]
- CognitiveClockBus: In-process publisher/subscriber bus for multi-frequency clock ticks.
- get_cognitive_clock_bus: Singleton getter for harness-wide clock bus.

[POS]
Harness runtime tier. Coordinates tick dispatching across T0-T3 tiers.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable

from myrm_agent_harness.runtime.cognitive_clock.cadence import (
    CognitiveCadence,
    CognitiveClockTaskSpec,
    CognitiveClockTickEvent,
)
from myrm_agent_harness.runtime.cognitive_clock.signals import (
    CooperativePauseSignal,
    get_global_pause_signal,
)

logger = logging.getLogger(__name__)

CadenceHandler = Callable[[CognitiveClockTickEvent, CooperativePauseSignal], Awaitable[None]]


class CognitiveClockBus:
    """Dispatches cognitive clock tick events to registered handlers per cadence."""

    def __init__(self) -> None:
        self._handlers: dict[CognitiveCadence, list[CadenceHandler]] = defaultdict(list)
        self._task_specs: dict[str, CognitiveClockTaskSpec] = {}
        self._pause_signal: CooperativePauseSignal = get_global_pause_signal()

    def register_task(
        self,
        spec: CognitiveClockTaskSpec,
        handler: CadenceHandler,
    ) -> None:
        """Register a background cognitive task handler for a given cadence."""
        self._task_specs[spec.task_id] = spec
        self._handlers[spec.cadence].append(handler)
        logger.debug(
            "Registered cognitive clock task %s under cadence %s",
            spec.task_id,
            spec.cadence.value,
        )

    async def emit_tick(
        self,
        cadence: CognitiveCadence,
        forced: bool = False,
        source: str = "scheduler",
    ) -> int:
        """Trigger a clock tick for the given cadence and invoke all registered handlers.

        Returns the number of handlers successfully completed.
        """
        handlers = self._handlers.get(cadence, [])
        if not handlers:
            return 0

        event = CognitiveClockTickEvent(
            cadence=cadence,
            tick_id=f"tick_{cadence.value}_{int(asyncio.get_event_loop().time() * 1000)}",
            forced=forced,
            source=source,
        )

        completed = 0
        for handler in handlers:
            try:
                # Cooperative pause check before dispatching each handler
                if not forced and self._pause_signal.is_pause_requested:
                    logger.info(
                        "CognitiveClockBus: skipping handler due to active pause signal (%s)",
                        self._pause_signal.pause_reason,
                    )
                    break

                await handler(event, self._pause_signal)
                completed += 1
            except Exception as exc:
                logger.error(
                    "CognitiveClockBus: error in %s handler: %s",
                    cadence.value,
                    exc,
                    exc_info=True,
                )

        return completed

    @property
    def registered_tasks(self) -> dict[str, CognitiveClockTaskSpec]:
        """Return shallow copy of all registered task specifications."""
        return dict(self._task_specs)


_GLOBAL_CLOCK_BUS: CognitiveClockBus | None = None


def get_cognitive_clock_bus() -> CognitiveClockBus:
    """Return or initialize global CognitiveClockBus singleton."""
    global _GLOBAL_CLOCK_BUS
    if _GLOBAL_CLOCK_BUS is None:
        _GLOBAL_CLOCK_BUS = CognitiveClockBus()
    return _GLOBAL_CLOCK_BUS
