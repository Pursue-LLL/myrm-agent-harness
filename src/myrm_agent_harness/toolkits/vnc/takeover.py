"""Takeover coordinator — state machine for human-agent browser control handoff.

[INPUT]
- asyncio (POS: event and timeout management)
- enum::StrEnum (POS: state enum)

[OUTPUT]
- TakeoverState: current control ownership enum
- TakeoverCoordinator: state machine managing AGENT_ACTIVE ↔ USER_TAKEOVER transitions

[POS]
Coordinates control handoff between the Agent and a human user during VNC sessions.
Prevents human-machine conflicts by pausing Agent browser tool calls during takeover.
Auto-reverts to Agent control after a configurable timeout.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable

logger = logging.getLogger(__name__)

_DEFAULT_TAKEOVER_TIMEOUT_S = 300  # 5 minutes


class TakeoverState(StrEnum):
    AGENT_ACTIVE = "agent_active"
    USER_TAKEOVER = "user_takeover"


TakeoverCallback = Callable[[TakeoverState], None]


@dataclass
class TakeoverInfo:
    """Public takeover status exposed to the business layer."""

    state: TakeoverState
    started_at: float | None = None
    timeout_s: int = _DEFAULT_TAKEOVER_TIMEOUT_S
    remaining_s: int | None = None


@dataclass
class TakeoverCoordinator:
    """State machine: AGENT_ACTIVE ↔ USER_TAKEOVER with auto-revert timeout.

    When a user requests takeover:
    1. State transitions to USER_TAKEOVER
    2. on_state_change callback fires (business layer pauses Agent browser ops)
    3. A timeout task starts; auto-reverts to AGENT_ACTIVE when expired
    4. User explicitly calls resume() or timeout fires → AGENT_ACTIVE
    """

    timeout_s: int = _DEFAULT_TAKEOVER_TIMEOUT_S
    on_state_change: TakeoverCallback | None = None
    _state: TakeoverState = field(default=TakeoverState.AGENT_ACTIVE, init=False)
    _takeover_started_at: float | None = field(default=None, init=False)
    _timeout_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    @property
    def state(self) -> TakeoverState:
        return self._state

    def get_info(self) -> TakeoverInfo:
        remaining: int | None = None
        if self._state == TakeoverState.USER_TAKEOVER and self._takeover_started_at:
            elapsed = time.monotonic() - self._takeover_started_at
            remaining = max(0, int(self.timeout_s - elapsed))
        return TakeoverInfo(
            state=self._state,
            started_at=self._takeover_started_at,
            timeout_s=self.timeout_s,
            remaining_s=remaining,
        )

    async def request_takeover(self) -> TakeoverInfo:
        """User requests control. Agent browser operations should pause."""
        async with self._lock:
            if self._state == TakeoverState.USER_TAKEOVER:
                return self.get_info()

            self._state = TakeoverState.USER_TAKEOVER
            self._takeover_started_at = time.monotonic()
            self._notify_state_change()

            if self._timeout_task and not self._timeout_task.done():
                self._timeout_task.cancel()
            self._timeout_task = asyncio.create_task(self._auto_revert())

            logger.info("Takeover: user assumed control (timeout=%ds)", self.timeout_s)
            return self.get_info()

    async def resume_agent(self) -> TakeoverInfo:
        """User returns control to Agent."""
        async with self._lock:
            return self._do_resume("user requested")

    def _do_resume(self, reason: str) -> TakeoverInfo:
        if self._state == TakeoverState.AGENT_ACTIVE:
            return self.get_info()

        if self._timeout_task and not self._timeout_task.done():
            self._timeout_task.cancel()
            self._timeout_task = None

        self._state = TakeoverState.AGENT_ACTIVE
        self._takeover_started_at = None
        self._notify_state_change()
        logger.info("Takeover: agent resumed control (%s)", reason)
        return self.get_info()

    def _notify_state_change(self) -> None:
        if self.on_state_change:
            try:
                self.on_state_change(self._state)
            except Exception:
                logger.exception("Takeover state change callback failed")

    async def _auto_revert(self) -> None:
        try:
            await asyncio.sleep(self.timeout_s)
            async with self._lock:
                if self._state == TakeoverState.USER_TAKEOVER:
                    self._do_resume("timeout")
        except asyncio.CancelledError:
            pass

    async def cleanup(self) -> None:
        """Cancel any pending timeout tasks."""
        if self._timeout_task and not self._timeout_task.done():
            self._timeout_task.cancel()
            self._timeout_task = None
