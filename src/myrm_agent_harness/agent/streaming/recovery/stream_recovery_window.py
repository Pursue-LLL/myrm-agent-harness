"""Recovery for provider rate-limit windows: wait exactly, park the goal, or fail fast.

[INPUT]
- toolkits.llms.errors.provider_window (POS: provider-stated retry boundary)
- toolkits.llms.errors.classifier (POS: error classification)
- agent.goals.wait_provider_window::park_goal_for_provider_window (POS: goal-side parking)
- agent.streaming.recovery.goal_session::goal_session_id (POS: goal lookup key of a run)
- observability.metrics.provider_window_metrics (POS: extractor drift alarm)

[OUTPUT]
- WindowAction: what the executor does after the handler ran
- ProviderWindowRecoveryMixin: `_handle_provider_window` and the cancel-aware sleep shared with transient retry

[POS]
Runs after model failover and before blind transient backoff. With a provider-stated
boundary the stream never guesses: a short wait is served exactly in-turn, a longer one
parks the running goal until the reset, and a boundary that cannot be waited out ends
the turn at once with the real reset time instead of burning minutes of useless retries.
"""

from __future__ import annotations

import asyncio
from enum import Enum, auto
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.goals.types import Goal, GoalStatus
from myrm_agent_harness.agent.goals.wait_provider_window import park_goal_for_provider_window
from myrm_agent_harness.agent.streaming.recovery.goal_session import goal_session_id
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.observability.metrics.provider_window_metrics import record_window_outcome
from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind, classify_error
from myrm_agent_harness.toolkits.llms.errors.provider_window import (
    ProviderWindowHint,
    WindowKind,
    extract_provider_window,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.agent.streaming.stream_compactor import StreamCompactor
    from myrm_agent_harness.agent.streaming.stream_executor import StreamContext

logger = get_agent_logger(__name__)

_WINDOW_ERROR_KINDS = frozenset({ErrorKind.RATE_LIMIT, ErrorKind.BILLING, ErrorKind.OVERLOADED})
_MAX_IN_TURN_WINDOW_WAITS = 3
_WAIT_MARGIN_S = 1.0
_SLEEP_SLICE_S = 0.1


class WindowAction(Enum):
    """Outcome of `_handle_provider_window` for the executor's handler chain."""

    PASS = auto()
    """No usable boundary: continue with the remaining handlers."""
    RETRY = auto()
    """Waited out the boundary in-turn: re-run the stream."""
    HELD = auto()
    """The goal is parked until the boundary: end the stream quietly."""
    FAIL = auto()
    """Boundary known but not waitable: surface the error now, skipping blind retries."""


class ProviderWindowRecoveryMixin:
    """Provider-window handling, mixed into StreamRecoveryMixin.

    Accesses StreamExecutor attributes via self: _ctx, _compactor, _window_waits,
    streaming_final_answer, _emit_recovery_event.
    """

    _ctx: StreamContext
    _compactor: StreamCompactor
    _window_waits: int
    streaming_final_answer: bool

    if TYPE_CHECKING:

        async def _emit_recovery_event(self, step_key: str, **extra: object) -> None: ...

    async def _handle_provider_window(self, exc: Exception) -> WindowAction:
        error_kind = classify_error(exc)
        if error_kind not in _WINDOW_ERROR_KINDS:
            return WindowAction.PASS

        hint = extract_provider_window(exc)
        if error_kind is not ErrorKind.OVERLOADED:
            record_window_outcome(hint.source.value if hint else "none")
        if hint is None:
            return WindowAction.PASS
        if error_kind is ErrorKind.BILLING and not hint.quota_window:
            # A Retry-After riding on a depleted balance is not a reset time.
            return WindowAction.PASS

        if hint.kind is WindowKind.IN_TURN:
            return await self._wait_in_turn(hint, error_kind)
        return await self._park_or_fail(hint)

    async def _wait_in_turn(self, hint: ProviderWindowHint, error_kind: ErrorKind) -> WindowAction:
        if self._window_waits >= _MAX_IN_TURN_WINDOW_WAITS:
            return WindowAction.PASS
        self._window_waits += 1

        delay_s = hint.wait_s + _WAIT_MARGIN_S
        logger.warning(
            " Provider window (%s, %s): waiting %.1fs for the stated reset (wait %d/%d)",
            error_kind.value,
            hint.source.value,
            delay_s,
            self._window_waits,
            _MAX_IN_TURN_WINDOW_WAITS,
        )
        await self._emit_recovery_event(
            "transient_retry",
            error_kind=error_kind.value,
            delay_ms=int(delay_s * 1000),
            restart=True,
        )
        if not await self._sleep_unless_cancelled(delay_s):
            return WindowAction.FAIL
        self.streaming_final_answer = False
        return WindowAction.RETRY

    async def _park_or_fail(self, hint: ProviderWindowHint) -> WindowAction:
        goal = await self._park_goal(hint)
        if goal is None:
            return WindowAction.FAIL

        logger.warning(
            " Provider window: goal %s -> %s until %.0f (source=%s)",
            goal.goal_id,
            goal.status.value,
            hint.reset_at,
            hint.source.value,
        )
        await self._emit_goal_status(goal)
        on_goal_hold = self._ctx.on_goal_hold
        if on_goal_hold is not None:
            try:
                await on_goal_hold(goal, hint)
            except Exception as exc:
                logger.warning("on_goal_hold callback failed for goal %s: %s", goal.goal_id, exc)
        return WindowAction.HELD if goal.status is GoalStatus.WAIT else WindowAction.FAIL

    async def _park_goal(self, hint: ProviderWindowHint) -> Goal | None:
        provider = self._ctx.goal_provider
        if provider is None:
            return None
        try:
            return await park_goal_for_provider_window(provider, goal_session_id(self._ctx), hint)
        except ValueError as exc:
            # The goal left ACTIVE concurrently (user paused or cancelled it): nothing to park.
            logger.warning("Provider window: goal can no longer be parked: %s", exc)
            return None

    async def _emit_goal_status(self, goal: Goal) -> None:
        waiting = goal.status is GoalStatus.WAIT
        await self._compactor.put(
            {
                "type": AgentEventType.GOAL_STATUS.value,
                "data": {
                    **goal.to_dict(),
                    "verdict": "wait" if waiting else "suppressed",
                    "reason": str(goal.metadata.get("wait_reason" if waiting else "pause_reason") or ""),
                    "should_continue": False,
                },
                "messageId": self._ctx.message_id,
            }
        )

    async def _sleep_unless_cancelled(self, seconds: float) -> bool:
        """Sleep *seconds* in short slices; False when the run was cancelled meanwhile."""
        cancel_token = self._ctx.cancel_token
        if cancel_token is None:
            await asyncio.sleep(seconds)
            return True
        steps = int(seconds / _SLEEP_SLICE_S)
        for _ in range(steps):
            if cancel_token.is_cancelled:
                return False
            await asyncio.sleep(_SLEEP_SLICE_S)
        remainder = seconds - steps * _SLEEP_SLICE_S
        if remainder > 0:
            await asyncio.sleep(remainder)
        return not cancel_token.is_cancelled
