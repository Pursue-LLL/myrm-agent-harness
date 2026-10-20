"""Provider-window recovery inside the streaming executor: exact wait, goal parking, fail-fast."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.goals.manager import GoalManager
from myrm_agent_harness.agent.goals.types import Goal, GoalStatus
from myrm_agent_harness.agent.streaming.recovery.stream_recovery_window import WindowAction
from myrm_agent_harness.agent.streaming.stream_executor import STREAM_DONE, StreamContext, StreamExecutor
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.types import AgentRunStatistics
from myrm_agent_harness.toolkits.llms.errors import MyrmLLMError
from myrm_agent_harness.toolkits.llms.errors.provider_window import ProviderWindowHint
from myrm_agent_harness.toolkits.storage.local import LocalStorageBackend

SLEEP_PATH = "myrm_agent_harness.agent.streaming.recovery.stream_recovery_window.asyncio.sleep"
CHAT_ID = "chat-1"


class _ProviderError(Exception):
    def __init__(
        self,
        message: str = "RateLimitError: rate limit exceeded (429)",
        *,
        headers: dict[str, str] | None = None,
        body: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.response = httpx.Response(429, headers=headers or {}, content=json.dumps(body or {}).encode())
        self.body = body


def _retry_after(seconds: int) -> _ProviderError:
    return _ProviderError(headers={"Retry-After": str(seconds)})


def _five_hour_window(wait_s: int) -> _ProviderError:
    return _ProviderError(
        headers={
            "anthropic-ratelimit-unified-5h-status": "rejected",
            "anthropic-ratelimit-unified-5h-reset": str(int(time.time()) + wait_s),
        }
    )


def _codex_window(wait_s: int) -> _ProviderError:
    body = {"error": {"type": "usage_limit_reached", "message": "usage limit", "resets_in_seconds": wait_s}}
    return _ProviderError("RateLimitError: 429 usage_limit_reached", body=body)


class FakeCompactor:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def put(self, event: object) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        pass

    def of_type(self, event_type: AgentEventType) -> list[dict[str, object]]:
        return [e for e in self.events if isinstance(e, dict) and e.get("type") == event_type.value]


@pytest.fixture
async def manager(tmp_path) -> GoalManager:
    return GoalManager(LocalStorageBackend(base_path=str(tmp_path)))


def _ctx(goal_provider: GoalManager | None = None, cancel_token: object | None = None) -> StreamContext:
    return StreamContext(
        agent=MagicMock(),
        agent_input={"messages": [HumanMessage(content="hello")]},
        merged_context={"locale": "en", "chat_id": CHAT_ID},
        run_config={},
        stats=AgentRunStatistics(),
        message_id="msg-1",
        cancel_token=cancel_token,  # type: ignore[arg-type]
        steering_token=None,
        source_tracker=MagicMock(),
        output_queue=asyncio.Queue(),
        goal_provider=goal_provider,
    )


def _executor(ctx: StreamContext) -> StreamExecutor:
    executor = StreamExecutor(ctx=ctx, fallback_llm=None, safety_fallback_llm=None, rebuild_agent_fn=MagicMock())
    executor._compactor = FakeCompactor()
    return executor


async def _astream_empty(*args: object, **kwargs: object) -> AsyncGenerator[object]:
    return
    yield


class TestInTurnWait:
    async def test_waits_the_stated_seconds_plus_margin_and_retries(self) -> None:
        executor = _executor(_ctx())
        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        with patch(SLEEP_PATH, fake_sleep):
            action = await executor._handle_provider_window(_retry_after(2))

        assert action is WindowAction.RETRY
        assert len(sleeps) == 1
        assert 2.9 < sleeps[0] <= 3.0
        (event,) = executor._compactor.of_type(AgentEventType.STATUS)
        assert event["step_key"] == "transient_retry"
        assert "attempt" not in event
        assert event["delay_ms"] == pytest.approx(3000, abs=100)

    async def test_wait_budget_is_three_then_falls_through(self) -> None:
        executor = _executor(_ctx())

        with patch(SLEEP_PATH, AsyncMock()):
            actions = [await executor._handle_provider_window(_retry_after(1)) for _ in range(4)]

        assert actions == [WindowAction.RETRY] * 3 + [WindowAction.PASS]

    async def test_cancellation_during_the_wait_fails_the_turn(self) -> None:
        token = MagicMock()
        token.is_cancelled = True
        executor = _executor(_ctx(cancel_token=token))

        assert await executor._handle_provider_window(_retry_after(5)) is WindowAction.FAIL


class TestNoBoundary:
    async def test_unhinted_rate_limit_is_left_to_transient_retry(self) -> None:
        assert await _executor(_ctx())._handle_provider_window(_ProviderError()) is WindowAction.PASS

    async def test_balance_exhaustion_with_retry_after_is_not_a_reset(self) -> None:
        exc = _ProviderError("insufficient_quota: you exceeded your current quota", headers={"Retry-After": "30"})

        assert await _executor(_ctx())._handle_provider_window(exc) is WindowAction.PASS

    async def test_non_rate_limit_errors_are_ignored(self) -> None:
        exc = _ProviderError("invalid api key (401)", headers={"Retry-After": "30"})

        assert await _executor(_ctx())._handle_provider_window(exc) is WindowAction.PASS


class TestGoalHold:
    async def _goal(self, manager: GoalManager) -> Goal:
        return await manager.create_goal(CHAT_ID, "finish the migration")

    async def test_goal_is_parked_and_the_host_is_told(self, manager: GoalManager) -> None:
        goal = await self._goal(manager)
        ctx = _ctx(manager)
        ctx.on_goal_hold = AsyncMock()
        executor = _executor(ctx)

        action = await executor._handle_provider_window(_five_hour_window(3600))

        assert action is WindowAction.HELD
        parked = await manager.get_goal(goal.goal_id)
        assert parked is not None
        assert parked.status is GoalStatus.WAIT
        assert parked.metadata["wait_kind"] == "usage_limit"
        ctx.on_goal_hold.assert_awaited_once()
        held_goal, hint = ctx.on_goal_hold.await_args.args
        assert held_goal.goal_id == goal.goal_id
        assert isinstance(hint, ProviderWindowHint)
        (status_event,) = executor._compactor.of_type(AgentEventType.GOAL_STATUS)
        assert status_event["data"]["status"] == "wait"
        assert status_event["data"]["verdict"] == "wait"

    async def test_codex_body_window_parks_too(self, manager: GoalManager) -> None:
        await self._goal(manager)

        action = await _executor(_ctx(manager))._handle_provider_window(_codex_window(7200))

        assert action is WindowAction.HELD

    async def test_a_reset_days_away_pauses_the_goal_and_fails_the_turn(self, manager: GoalManager) -> None:
        goal = await self._goal(manager)
        ctx = _ctx(manager)
        ctx.on_goal_hold = AsyncMock()

        action = await _executor(ctx)._handle_provider_window(_codex_window(5 * 86400))

        assert action is WindowAction.FAIL
        paused = await manager.get_goal(goal.goal_id)
        assert paused is not None
        assert paused.status is GoalStatus.PAUSED
        ctx.on_goal_hold.assert_awaited_once()

    async def test_without_a_goal_a_long_boundary_fails_fast(self) -> None:
        action = await _executor(_ctx())._handle_provider_window(_five_hour_window(3600))

        assert action is WindowAction.FAIL

    async def test_a_goal_paused_meanwhile_fails_the_turn(self, manager: GoalManager) -> None:
        goal = await self._goal(manager)
        await manager.update_status(goal.goal_id, GoalStatus.PAUSED)

        action = await _executor(_ctx(manager))._handle_provider_window(_five_hour_window(3600))

        assert action is WindowAction.FAIL

    async def test_host_callback_failure_does_not_unpark_the_goal(self, manager: GoalManager) -> None:
        goal = await self._goal(manager)
        ctx = _ctx(manager)
        ctx.on_goal_hold = AsyncMock(side_effect=RuntimeError("notify down"))

        action = await _executor(ctx)._handle_provider_window(_five_hour_window(3600))

        assert action is WindowAction.HELD
        parked = await manager.get_goal(goal.goal_id)
        assert parked is not None
        assert parked.status is GoalStatus.WAIT

    async def test_goal_is_found_under_the_chat_id_not_the_message_id(self, manager: GoalManager) -> None:
        goal = await self._goal(manager)
        ctx = _ctx(manager)

        assert ctx.message_id != CHAT_ID
        await _executor(ctx)._handle_provider_window(_five_hour_window(3600))

        parked = await manager.get_goal(goal.goal_id)
        assert parked is not None
        assert parked.status is GoalStatus.WAIT


@pytest.fixture(autouse=True)
def _no_hooks():
    with patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock):
        yield


class TestExecuteLoop:
    async def test_stream_resumes_after_the_exact_wait(self) -> None:
        ctx = _ctx()
        executor = _executor(ctx)
        calls = 0

        async def astream(*args: object, **kwargs: object) -> AsyncGenerator[object]:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise _retry_after(2)
            yield ("messages", (AIMessage(content="ok"), {"tags": []}))

        ctx.agent.astream = astream
        with (
            patch(SLEEP_PATH, AsyncMock()),
            patch.object(executor, "_dispatch_chunk", new_callable=AsyncMock) as dispatch,
        ):
            await executor.execute()

        assert calls == 2
        dispatch.assert_called_once()
        assert not executor._compactor.of_type(AgentEventType.ERROR)
        assert executor._compactor.events[-1] is STREAM_DONE

    async def test_held_goal_ends_the_stream_without_an_error(self, manager: GoalManager) -> None:
        goal = await manager.create_goal(CHAT_ID, "finish the migration")
        ctx = _ctx(manager)
        executor = _executor(ctx)
        calls = 0

        async def astream(*args: object, **kwargs: object) -> AsyncGenerator[object]:
            nonlocal calls
            calls += 1
            raise _five_hour_window(3600)
            yield

        ctx.agent.astream = astream
        await executor.execute()

        assert calls == 1
        assert not executor._compactor.of_type(AgentEventType.ERROR)
        assert executor._compactor.events[-1] is STREAM_DONE
        parked = await manager.get_goal(goal.goal_id)
        assert parked is not None
        assert parked.status is GoalStatus.WAIT
        assert parked.turns_used == goal.turns_used

        await manager.exit_wait(goal.goal_id)
        woken = await manager.get_goal(goal.goal_id)
        assert woken is not None
        assert woken.status is GoalStatus.ACTIVE
        assert woken.turns_used == goal.turns_used

    async def test_unwaitable_boundary_surfaces_the_real_reset_time_at_once(self) -> None:
        ctx = _ctx()
        executor = _executor(ctx)
        calls = 0

        async def astream(*args: object, **kwargs: object) -> AsyncGenerator[object]:
            nonlocal calls
            calls += 1
            raise _codex_window(5 * 86400)
            yield

        ctx.agent.astream = astream
        with pytest.raises(MyrmLLMError):
            await executor.execute()

        assert calls == 1
        (error_event,) = executor._compactor.of_type(AgentEventType.ERROR)
        assert error_event["cooldown_remaining_ms"] == pytest.approx(5 * 86400 * 1000, rel=0.01)
