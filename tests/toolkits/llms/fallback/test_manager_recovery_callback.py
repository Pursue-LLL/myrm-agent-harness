"""Unit tests for ModelFallbackManager recovery callback."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.llms.fallback.events import RecoveryEvent
from myrm_agent_harness.toolkits.llms.fallback.manager import ModelFallbackManager
from myrm_agent_harness.toolkits.llms.fallback.scenario import ScenarioType


@pytest.mark.asyncio
async def test_manager_recovery_callback_triggered() -> None:
    """Test that recovery callback is triggered when probe succeeds."""
    call_count = 0

    async def mock_call_fn():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("Rate limit")
        return "success"

    recovery_callback = AsyncMock()

    manager = ModelFallbackManager[str](on_recovery=recovery_callback)

    # Add a single candidate
    manager.add_candidate(
        name="gpt-4",
        call_fn=mock_call_fn,
        priority=0,
        cost=0.5,
        latency=0.8,
        quality=0.9,
    )

    # First call - fails and enters cooldown
    with pytest.raises(Exception):
        await manager.execute(scenario=ScenarioType.BALANCED, now_ms=1000.0)

    # Second call - probe succeeds (simulate 70s passing, past global throttle but still in cooldown)
    result = await manager.execute(scenario=ScenarioType.BALANCED, now_ms=71000.0)

    assert result == "success"
    assert recovery_callback.called
    assert recovery_callback.call_count == 1

    # Verify recovery event
    recovery_event: RecoveryEvent = recovery_callback.call_args[0][0]
    assert recovery_event.model == "gpt-4"
    assert recovery_event.downtime_ms > 0
    assert recovery_event.probe_count > 0
    assert recovery_event.was_in_cooldown is True


@pytest.mark.asyncio
async def test_manager_recovery_callback_not_triggered_on_normal_success() -> None:
    """Test that recovery callback is NOT triggered on normal success."""

    async def mock_call_fn():
        return "success"

    recovery_callback = AsyncMock()

    manager = ModelFallbackManager[str](on_recovery=recovery_callback)

    manager.add_candidate(
        name="gpt-4",
        call_fn=mock_call_fn,
        priority=0,
        cost=0.5,
        latency=0.8,
        quality=0.9,
    )

    # Call succeeds without prior failure
    result = await manager.execute(scenario=ScenarioType.BALANCED)

    assert result == "success"
    assert not recovery_callback.called


@pytest.mark.asyncio
async def test_manager_recovery_callback_exception_handling() -> None:
    """Test that recovery callback exception doesn't fail the request."""
    call_count = 0

    async def mock_call_fn():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("Rate limit")
        return "success"

    async def failing_callback(event: RecoveryEvent) -> None:
        raise RuntimeError("Callback error")

    manager = ModelFallbackManager[str](on_recovery=failing_callback)

    # Use different model name to avoid global throttle conflict
    manager.add_candidate(
        name="claude-3-opus",
        call_fn=mock_call_fn,
        priority=0,
        cost=0.5,
        latency=0.8,
        quality=0.9,
    )

    # First call fails
    with pytest.raises(Exception):
        await manager.execute(scenario=ScenarioType.BALANCED, now_ms=1000.0)

    # Second call succeeds despite callback failure (70s later, past global throttle)
    result = await manager.execute(scenario=ScenarioType.BALANCED, now_ms=71000.0)
    assert result == "success"
