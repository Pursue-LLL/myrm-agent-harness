"""Tests for ToolFallbackRegistry."""

import time
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.skills.evolution.quality.fallback import (
    FallbackChain,
    ToolFallbackRegistry,
)


@pytest.fixture
def registry():
    reg = ToolFallbackRegistry()
    reg.register_fallback("primary", ["fallback_1", "fallback_2"], cache_ttl=1)
    return reg

def test_fallback_chain_order():
    chain = FallbackChain("primary", ["fallback_1", "fallback_2"])

    # Initial order
    assert chain.get_execution_order() == ["primary", "fallback_1", "fallback_2"]

    # Mark fallback_2 as success
    chain.mark_success("fallback_2")
    assert chain.get_execution_order() == ["fallback_2", "primary", "fallback_1"]

def test_fallback_cache():
    chain = FallbackChain("primary", ["fallback_1"], cache_ttl=1)

    # Not cached
    assert chain.get_cache("key1") is None

    # Set cache
    chain.set_cache("key1", "result1")
    assert chain.get_cache("key1") == "result1"

    # Expire
    chain._cache["key1"] = ("result1", time.time() - 2)
    assert chain.get_cache("key1") is None

@pytest.mark.asyncio
async def test_execute_primary_success(registry):
    executor = AsyncMock()
    executor.side_effect = lambda t: f"result_{t}"

    res, tool = await registry.execute_with_fallback("primary", executor)
    assert res == "result_primary"
    assert tool == "primary"

    stats = registry.get_stats()
    assert stats["total_fallbacks"] == 0

@pytest.mark.asyncio
async def test_execute_fallback_success(registry):
    async def executor(tool):
        if tool == "primary":
            raise Exception("Primary failed")
        return f"result_{tool}"

    res, tool = await registry.execute_with_fallback("primary", executor)
    assert res == "result_fallback_1"
    assert tool == "fallback_1"

    stats = registry.get_stats()
    assert stats["total_fallbacks"] == 1
    assert stats["fallback_success_count"] == 1
    assert stats["fallback_success_rate"] == 1.0

@pytest.mark.asyncio
async def test_execute_all_fail(registry):
    executor = AsyncMock(side_effect=Exception("All fail"))

    with pytest.raises(Exception, match="All fail"):
        await registry.execute_with_fallback("primary", executor)

    stats = registry.get_stats()
    assert stats["total_fallbacks"] == 1
    assert stats["fallback_success_count"] == 0
    assert stats["fallback_success_rate"] == 0.0

@pytest.mark.asyncio
async def test_execute_no_fallback(registry):
    executor = AsyncMock(return_value="direct_result")

    res, tool = await registry.execute_with_fallback("unknown_tool", executor)
    assert res == "direct_result"
    assert tool == "unknown_tool"

@pytest.mark.asyncio
async def test_execute_with_cache(registry):
    async def executor(tool):
        return "cache_me"

    # First call sets cache
    res1, _tool1 = await registry.execute_with_fallback("primary", executor, cache_key="k1")
    assert res1 == "cache_me"

    # Second call uses cache
    res2, tool2 = await registry.execute_with_fallback("primary", executor, cache_key="k1")
    assert res2 == "cache_me"
    assert tool2 == "primary:cache"
