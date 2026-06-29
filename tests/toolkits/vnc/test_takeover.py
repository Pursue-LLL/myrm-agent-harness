"""Unit tests for TakeoverCoordinator lifecycle hooks and state machine."""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.toolkits.vnc.takeover import (
    TakeoverCoordinator,
    TakeoverState,
)


@pytest.fixture
def coordinator() -> TakeoverCoordinator:
    return TakeoverCoordinator(timeout_s=2)


class TestTakeoverStateMachine:
    @pytest.mark.asyncio
    async def test_initial_state_is_agent_active(self, coordinator: TakeoverCoordinator) -> None:
        assert coordinator.state == TakeoverState.AGENT_ACTIVE

    @pytest.mark.asyncio
    async def test_request_takeover_transitions_state(self, coordinator: TakeoverCoordinator) -> None:
        info = await coordinator.request_takeover(reason="test reason")
        assert info.state == TakeoverState.USER_TAKEOVER
        assert coordinator.state == TakeoverState.USER_TAKEOVER

    @pytest.mark.asyncio
    async def test_resume_returns_to_agent_active(self, coordinator: TakeoverCoordinator) -> None:
        await coordinator.request_takeover()
        info = await coordinator.resume_agent()
        assert info.state == TakeoverState.AGENT_ACTIVE
        assert coordinator.state == TakeoverState.AGENT_ACTIVE

    @pytest.mark.asyncio
    async def test_request_takeover_is_idempotent(self, coordinator: TakeoverCoordinator) -> None:
        await coordinator.request_takeover(reason="first")
        info = await coordinator.request_takeover(reason="second")
        assert info.state == TakeoverState.USER_TAKEOVER

    @pytest.mark.asyncio
    async def test_resume_when_already_active_is_noop(self, coordinator: TakeoverCoordinator) -> None:
        info = await coordinator.resume_agent()
        assert info.state == TakeoverState.AGENT_ACTIVE


class TestLifecycleHooks:
    @pytest.mark.asyncio
    async def test_on_takeover_start_fires_with_reason(self) -> None:
        received: list[str] = []

        async def hook(reason: str) -> None:
            received.append(reason)

        coord = TakeoverCoordinator(timeout_s=60, on_takeover_start=hook)
        await coord.request_takeover(reason="user stuck")
        await coord.cleanup()

        assert received == ["user stuck"]

    @pytest.mark.asyncio
    async def test_on_takeover_end_fires_on_resume(self) -> None:
        received: list[str] = []

        async def hook(reason: str) -> None:
            received.append(reason)

        coord = TakeoverCoordinator(timeout_s=60, on_takeover_end=hook)
        await coord.request_takeover(reason="help needed")
        await coord.resume_agent()
        await coord.cleanup()

        assert received == ["help needed"]

    @pytest.mark.asyncio
    async def test_on_takeover_end_fires_on_timeout(self) -> None:
        received: list[str] = []

        async def hook(reason: str) -> None:
            received.append(reason)

        coord = TakeoverCoordinator(timeout_s=0.1, on_takeover_end=hook)
        await coord.request_takeover(reason="timeout test")
        await asyncio.sleep(0.3)

        assert received == ["timeout test"]
        assert coord.state == TakeoverState.AGENT_ACTIVE

    @pytest.mark.asyncio
    async def test_hooks_not_fired_when_none(self) -> None:
        coord = TakeoverCoordinator(timeout_s=60)
        await coord.request_takeover(reason="no hooks")
        await coord.resume_agent()
        await coord.cleanup()

    @pytest.mark.asyncio
    async def test_hook_exception_does_not_break_flow(self) -> None:
        async def bad_hook(reason: str) -> None:
            raise RuntimeError("hook error")

        coord = TakeoverCoordinator(
            timeout_s=60,
            on_takeover_start=bad_hook,
            on_takeover_end=bad_hook,
        )
        info = await coord.request_takeover(reason="error test")
        assert info.state == TakeoverState.USER_TAKEOVER

        info = await coord.resume_agent()
        assert info.state == TakeoverState.AGENT_ACTIVE
        await coord.cleanup()

    @pytest.mark.asyncio
    async def test_reason_cleared_after_resume(self) -> None:
        received_start: list[str] = []
        received_end: list[str] = []

        async def start_hook(reason: str) -> None:
            received_start.append(reason)

        async def end_hook(reason: str) -> None:
            received_end.append(reason)

        coord = TakeoverCoordinator(
            timeout_s=60,
            on_takeover_start=start_hook,
            on_takeover_end=end_hook,
        )

        await coord.request_takeover(reason="first")
        await coord.resume_agent()

        await coord.request_takeover(reason="second")
        await coord.resume_agent()
        await coord.cleanup()

        assert received_start == ["first", "second"]
        assert received_end == ["first", "second"]


class TestStateChangeCallback:
    @pytest.mark.asyncio
    async def test_on_state_change_fires(self) -> None:
        states: list[TakeoverState] = []

        def callback(state: TakeoverState) -> None:
            states.append(state)

        coord = TakeoverCoordinator(timeout_s=60, on_state_change=callback)
        await coord.request_takeover()
        await coord.resume_agent()
        await coord.cleanup()

        assert states == [TakeoverState.USER_TAKEOVER, TakeoverState.AGENT_ACTIVE]


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_start_hook_not_fired_on_idempotent_call(self) -> None:
        received: list[str] = []

        async def hook(reason: str) -> None:
            received.append(reason)

        coord = TakeoverCoordinator(timeout_s=60, on_takeover_start=hook)
        await coord.request_takeover(reason="first")
        await coord.request_takeover(reason="second")
        await coord.cleanup()

        assert received == ["first"]

    @pytest.mark.asyncio
    async def test_end_hook_not_fired_on_noop_resume(self) -> None:
        received: list[str] = []

        async def hook(reason: str) -> None:
            received.append(reason)

        coord = TakeoverCoordinator(timeout_s=60, on_takeover_end=hook)
        await coord.resume_agent()
        await coord.cleanup()

        assert received == []

    @pytest.mark.asyncio
    async def test_get_info_remaining_s_decreases(self) -> None:
        coord = TakeoverCoordinator(timeout_s=10)
        await coord.request_takeover()
        info1 = coord.get_info()
        await asyncio.sleep(0.1)
        info2 = coord.get_info()
        await coord.cleanup()

        assert info1.remaining_s is not None
        assert info2.remaining_s is not None
        assert info2.remaining_s <= info1.remaining_s

    @pytest.mark.asyncio
    async def test_empty_reason_default(self) -> None:
        received_start: list[str] = []
        received_end: list[str] = []

        async def start_hook(reason: str) -> None:
            received_start.append(reason)

        async def end_hook(reason: str) -> None:
            received_end.append(reason)

        coord = TakeoverCoordinator(
            timeout_s=60, on_takeover_start=start_hook, on_takeover_end=end_hook
        )
        await coord.request_takeover()
        await coord.resume_agent()
        await coord.cleanup()

        assert received_start == [""]
        assert received_end == [""]

    @pytest.mark.asyncio
    async def test_new_takeover_after_resume_starts_fresh_timeout(self) -> None:
        coord = TakeoverCoordinator(timeout_s=0.2)
        await coord.request_takeover(reason="first")
        await coord.resume_agent()

        await coord.request_takeover(reason="second")
        assert coord.state == TakeoverState.USER_TAKEOVER

        await asyncio.sleep(0.3)
        assert coord.state == TakeoverState.AGENT_ACTIVE

    @pytest.mark.asyncio
    async def test_concurrent_takeover_requests(self) -> None:
        call_count = 0

        async def hook(reason: str) -> None:
            nonlocal call_count
            call_count += 1

        coord = TakeoverCoordinator(timeout_s=60, on_takeover_start=hook)
        results = await asyncio.gather(
            coord.request_takeover(reason="a"),
            coord.request_takeover(reason="b"),
            coord.request_takeover(reason="c"),
        )
        await coord.cleanup()

        assert all(r.state == TakeoverState.USER_TAKEOVER for r in results)
        assert call_count == 1


class TestAutoRevert:
    @pytest.mark.asyncio
    async def test_auto_revert_after_timeout(self) -> None:
        coord = TakeoverCoordinator(timeout_s=0.1)
        await coord.request_takeover()
        assert coord.state == TakeoverState.USER_TAKEOVER

        await asyncio.sleep(0.3)
        assert coord.state == TakeoverState.AGENT_ACTIVE

    @pytest.mark.asyncio
    async def test_cleanup_cancels_timeout(self) -> None:
        coord = TakeoverCoordinator(timeout_s=0.1)
        await coord.request_takeover()
        await coord.cleanup()
        await asyncio.sleep(0.2)
