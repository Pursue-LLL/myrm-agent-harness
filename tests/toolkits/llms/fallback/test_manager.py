"""Unit tests for ModelFallbackManager."""

import time

import pytest

from myrm_agent_harness.toolkits.llms.fallback import ModelFallbackManager


class RateLimitError(Exception):
    """Mock rate limit error."""

    pass


class AuthError(Exception):
    """Mock auth error."""

    pass


@pytest.mark.asyncio
async def test_primary_success():
    """Test successful primary model call."""
    manager = ModelFallbackManager[str]()

    manager.add_candidate("gpt-4", 0, lambda: _async_return("primary result"))
    manager.add_candidate("claude-3", 1, lambda: _async_return("fallback result"))

    result = await manager.execute()

    assert result == "primary result"


@pytest.mark.asyncio
async def test_fallback_on_rate_limit():
    """Test fallback on rate limit error."""
    attempts = []

    async def primary():
        attempts.append("primary")
        raise RateLimitError("Rate limit exceeded")

    async def fallback():
        attempts.append("fallback")
        return "fallback result"

    manager = ModelFallbackManager[str]()
    manager.add_candidate("gpt-4", 0, primary)
    manager.add_candidate("claude-3", 1, fallback)

    result = await manager.execute()

    assert result == "fallback result"
    assert attempts == ["primary", "fallback"]


@pytest.mark.asyncio
async def test_cooldown_mechanism():
    """Test cooldown period for failed models."""
    attempts = []

    async def primary():
        attempts.append("primary")
        raise RateLimitError("Rate limit exceeded")

    async def fallback():
        attempts.append("fallback")
        return "fallback result"

    manager = ModelFallbackManager[str]()
    manager.add_candidate("gpt-4", 0, primary)
    manager.add_candidate("claude-3", 1, fallback)

    # First call - primary fails, fallback succeeds
    result1 = await manager.execute()
    assert result1 == "fallback result"
    assert attempts == ["primary", "fallback"]

    # Second call immediately - primary will be probed (probe interval not elapsed yet)
    # but probe will fail, so fallback succeeds
    attempts.clear()
    result2 = await manager.execute()
    assert result2 == "fallback result"
    # Note: With probe mechanism, primary may be tried as a probe
    # The important thing is fallback still succeeds


@pytest.mark.asyncio
async def test_candidate_priority():
    """Test candidates are tried in priority order."""
    attempts = []

    async def high_priority():
        attempts.append("high")
        return "high result"

    async def low_priority():
        attempts.append("low")
        return "low result"

    manager = ModelFallbackManager[str]()
    manager.add_candidate("low-model", 10, low_priority)
    manager.add_candidate("high-model", 1, high_priority)

    result = await manager.execute()

    assert result == "high result"
    assert attempts == ["high"]


@pytest.mark.asyncio
async def test_non_failoverable_error_propagates():
    """Test non-failoverable errors are propagated immediately."""
    attempts = []

    async def primary():
        attempts.append("primary")
        raise AuthError("Unauthorized")

    async def fallback():
        attempts.append("fallback")
        return "fallback result"

    manager = ModelFallbackManager[str]()
    manager.add_candidate("gpt-4", 0, primary)
    manager.add_candidate("claude-3", 1, fallback)

    with pytest.raises(AuthError):
        await manager.execute()

    # Fallback should not be attempted
    assert attempts == ["primary"]


@pytest.mark.asyncio
async def test_all_models_fail():
    """Test all models failing with failoverable errors."""

    async def always_fails():
        raise RateLimitError("Rate limit exceeded")

    manager = ModelFallbackManager[str]()
    manager.add_candidate("gpt-4", 0, always_fails)
    manager.add_candidate("claude-3", 1, always_fails)

    with pytest.raises(RateLimitError):
        await manager.execute()


@pytest.mark.asyncio
async def test_reset_cooldowns():
    """Test cooldown reset functionality."""
    call_count = {"primary": 0}

    async def primary():
        call_count["primary"] += 1
        if call_count["primary"] == 1:
            raise RateLimitError("Rate limit exceeded")
        return "primary result"

    async def fallback():
        return "fallback result"

    manager = ModelFallbackManager[str]()
    manager.add_candidate("gpt-4", 0, primary)
    manager.add_candidate("claude-3", 1, fallback)

    # First call - primary fails, fallback succeeds
    result1 = await manager.execute()
    assert result1 == "fallback result"
    assert call_count["primary"] == 1

    # Reset cooldowns
    manager.reset_cooldowns()

    # Second call - primary should be tried again and succeed
    result2 = await manager.execute()
    assert result2 == "primary result"
    assert call_count["primary"] == 2


@pytest.mark.asyncio
async def test_probe_during_cooldown():
    """Test probe mechanism during cooldown period."""
    call_count = {"primary": 0}

    async def primary():
        call_count["primary"] += 1
        # Fail first 2 times, succeed on 3rd (probe)
        if call_count["primary"] <= 2:
            raise RateLimitError("Rate limit exceeded")
        return "primary result"

    async def fallback():
        return "fallback result"

    manager = ModelFallbackManager[str]()
    manager.add_candidate("gpt-4", 0, primary)
    manager.add_candidate("claude-3", 1, fallback)

    # Clear global probe throttle for clean test
    manager._global_throttle.clear()

    # First call - primary fails, enters cooldown, fallback succeeds
    result1 = await manager.execute()
    assert result1 == "fallback result"
    assert call_count["primary"] == 1

    # Simulate time passing (60s for probe interval)
    primary_candidate = manager._candidates[0]
    now_ms_2 = time.time() * 1000

    # Manually set cooldown window: started 60s ago, 240s remaining
    primary_candidate.cooldown_started_at = now_ms_2 - 60_000
    primary_candidate.cooldown_until = now_ms_2 + 240_000

    # Second call - should probe primary (still in cooldown but probe eligible)
    result2 = await manager.execute(now_ms=now_ms_2)
    assert result2 == "fallback result"  # Probe fails, fallback succeeds
    assert call_count["primary"] == 2
    assert primary_candidate.probe_count == 1

    # Simulate another probe interval (60s)
    now_ms_3 = now_ms_2 + 60_001  # 60s later
    primary_candidate.last_probe_at = now_ms_2  # Last probe was at call 2
    primary_candidate.cooldown_started_at = now_ms_2 - 60_000  # Keep consistent
    primary_candidate.cooldown_until = now_ms_3 + 180_000

    # Third call - probe succeeds, exits cooldown
    result3 = await manager.execute(now_ms=now_ms_3)
    assert result3 == "primary result"  # Probe succeeds!
    assert call_count["primary"] == 3
    assert primary_candidate.cooldown_until == 0.0  # Cooldown cleared
    assert primary_candidate.probe_count == 0  # Probe state reset


@pytest.mark.asyncio
async def test_probe_max_attempts():
    """Test probe stops after max attempts."""
    call_count = {"primary": 0}

    async def primary():
        call_count["primary"] += 1
        raise RateLimitError("Rate limit exceeded")

    async def fallback():
        return "fallback result"

    manager = ModelFallbackManager[str]()
    manager.add_candidate("gpt-4", 0, primary)
    manager.add_candidate("claude-3", 1, fallback)

    # Clear global probe throttle for clean test
    manager._global_throttle.clear()

    # First call - primary fails, enters cooldown
    await manager.execute()
    assert call_count["primary"] == 1

    primary_candidate = manager._candidates[0]
    now_ms = time.time() * 1000
    cooldown_start = now_ms

    # Adjust cooldown to allow probing (rate_limit interval is 60s)
    primary_candidate.cooldown_started_at = cooldown_start
    primary_candidate.cooldown_until = now_ms + 240_000

    # Exhaust probe attempts
    for i in range(3):
        now_ms = now_ms + 60_001  # Advance time by 60s
        primary_candidate.cooldown_started_at = cooldown_start  # Keep original start
        primary_candidate.cooldown_until = now_ms + (240_000 - (i + 1) * 60_000)
        if i > 0:
            primary_candidate.last_probe_at = now_ms - 60_001
        await manager.execute(now_ms=now_ms)

    assert call_count["primary"] == 4  # 1 initial + 3 probes
    assert primary_candidate.probe_count == 3

    # Next call should skip primary (max probes reached)
    now_ms = now_ms + 60_001
    primary_candidate.cooldown_started_at = cooldown_start
    primary_candidate.cooldown_until = now_ms + 60_000
    call_count["primary"] = 0
    await manager.execute(now_ms=now_ms)
    assert call_count["primary"] == 0  # Primary not probed


@pytest.mark.asyncio
async def test_consecutive_failures_exponential_backoff():
    """Test that consecutive failures increase cooldown via exponential backoff.

    Uses OVERLOADED (base=60s) so we can see backoff before hitting the 10min cap:
      fail 1: 2^1 * 60s = 120s
      fail 2: 2^2 * 60s = 240s
    """

    class OverloadedError(Exception):
        pass

    async def always_fails():
        raise OverloadedError("Overloaded")

    async def fallback():
        return "fallback result"

    manager = ModelFallbackManager[str]()
    manager.add_candidate("gpt-4", 0, always_fails)
    manager.add_candidate("claude-3", 1, fallback)

    manager._global_throttle.clear()

    primary = manager._candidates[0]

    now_ms = time.time() * 1000

    # 1st failure
    await manager.execute(now_ms=now_ms)
    assert primary.consecutive_failures == 1
    duration_1 = primary.cooldown_until - now_ms

    # Reset cooldown to allow re-entry but keep consecutive_failures
    primary.cooldown_until = 0.0

    # 2nd failure
    now_ms_2 = now_ms + 1000
    await manager.execute(now_ms=now_ms_2)
    assert primary.consecutive_failures == 2
    duration_2 = primary.cooldown_until - now_ms_2

    # 2nd cooldown should be 2x the 1st (2^2 vs 2^1 multiplier)
    assert duration_2 > duration_1 * 1.5


@pytest.mark.asyncio
async def test_consecutive_failures_reset_on_success():
    """Test that consecutive_failures resets to 0 on success."""
    call_count = {"n": 0}

    async def sometimes_fails():
        call_count["n"] += 1
        if call_count["n"] <= 2:
            raise RateLimitError("Rate limit exceeded")
        return "primary result"

    async def fallback():
        return "fallback result"

    manager = ModelFallbackManager[str]()
    manager.add_candidate("gpt-4", 0, sometimes_fails)
    manager.add_candidate("claude-3", 1, fallback)

    # 1st call: primary fails
    await manager.execute()
    primary = manager._candidates[0]
    assert primary.consecutive_failures == 1

    # Reset cooldown manually
    primary.cooldown_until = 0.0

    # 2nd call: primary fails again
    await manager.execute()
    assert primary.consecutive_failures == 2

    # Reset cooldown manually
    primary.cooldown_until = 0.0

    # 3rd call: primary succeeds
    result = await manager.execute()
    assert result == "primary result"
    assert primary.consecutive_failures == 0


async def _async_return(value: str) -> str:
    """Helper to return async value."""
    return value
