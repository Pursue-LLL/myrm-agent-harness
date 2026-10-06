"""Screen lock / sleep guard in front of every physical input and capture.

[INPUT]
- backends.protocols::ComputerBackend (POS: is_screen_locked / is_display_asleep probes)
- safety::SCREEN_LOCKED_REFUSAL, DISPLAY_SLEEPING_REFUSAL, SNAPSHOT_SCREEN_LOCKED_REFUSAL, SNAPSHOT_DISPLAY_SLEEPING_REFUSAL (POS: Desktop safety guardrail layer)
- types::ScreenUnlockCallback (POS: host-provided on-demand unlock)

[OUTPUT]
- ScreenGuard: lock / sleep probes, one host unlock attempt per locked probe, model-facing refusals

[POS]
Single owner of the "is the physical screen usable" decision for ComputerSession and
DesktopSession, so both refuse (or recover) identically. The harness never unlocks a
screen itself: the host decides whether and how, and the guard re-probes afterwards.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from myrm_agent_harness.toolkits.computer_use.backends.protocols import ComputerBackend
from myrm_agent_harness.toolkits.computer_use.safety import (
    DISPLAY_SLEEPING_REFUSAL,
    SCREEN_LOCKED_REFUSAL,
    SNAPSHOT_DISPLAY_SLEEPING_REFUSAL,
    SNAPSHOT_SCREEN_LOCKED_REFUSAL,
)
from myrm_agent_harness.toolkits.computer_use.types import ScreenUnlockCallback

logger = logging.getLogger(__name__)

# (locked, sleeping) refusal texts returned to the model by desktop tools.
_INPUT_REFUSALS = (SCREEN_LOCKED_REFUSAL, DISPLAY_SLEEPING_REFUSAL)
_SNAPSHOT_REFUSALS = (SNAPSHOT_SCREEN_LOCKED_REFUSAL, SNAPSHOT_DISPLAY_SLEEPING_REFUSAL)


class ScreenGuard:
    """Lock / sleep probes with an optional host-provided unlock recovery."""

    def __init__(self, backend: ComputerBackend, on_unlocked: Callable[[], None]) -> None:
        self._backend = backend
        self._on_unlocked = on_unlocked
        self.unlock_callback: ScreenUnlockCallback | None = None

    def is_locked(self) -> bool:
        return self._probe("is_screen_locked")

    def is_sleeping(self) -> bool:
        return self._probe("is_display_asleep")

    async def refusal(self, *, snapshot: bool = False) -> str | None:
        """The refusal text for an unusable screen, or None when the action may proceed.

        A locked screen first gets the on-demand unlock attempt; a sleeping display never does.
        """
        locked_text, sleeping_text = _SNAPSHOT_REFUSALS if snapshot else _INPUT_REFUSALS
        if await self.still_locked():
            return locked_text
        if self.is_sleeping():
            return sleeping_text
        return None

    async def still_locked(self) -> bool:
        """Whether the screen is locked even after the host had one chance to unlock it.

        Only the re-probe decides, never the callback: a host that claims success while the
        screen is still locked cannot open the guard, and a failing host leaves it closed.
        A successful recovery discards the visual state cached before the lock.
        """
        if not self.is_locked():
            return False
        if self.unlock_callback is None:
            return True
        try:
            await self.unlock_callback()
        except Exception as exc:  # a broken host hook must keep the guard closed, not crash the tool call
            logger.warning("[SAFETY_GUARD] Screen unlock callback failed: %s", exc)
            return True
        if self.is_locked():
            return True
        logger.info("[SAFETY_GUARD] Screen unlocked on demand")
        self._on_unlocked()
        return False

    def _probe(self, name: str) -> bool:
        probe = getattr(self._backend, name, None)
        value = probe() if callable(probe) else False
        return value if isinstance(value, bool) else False
