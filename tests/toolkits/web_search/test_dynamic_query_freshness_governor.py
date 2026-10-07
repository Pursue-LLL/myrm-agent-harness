"""Unit tests for Dynamic Query Freshness and Search Cache Governor.

Verifies natural-language prompt bypass, realtime keyword detection, short-TTL expiration,
and single-flight stampede defense under cache-bypass mode.
"""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.toolkits.web_search.coalescing.freshness_intent_types import (
    FreshnessGovernorConfig,
    QueryFreshnessTier,
)
from myrm_agent_harness.toolkits.web_search.coalescing.query_freshness_detector import (
    QueryFreshnessDetector,
)
from myrm_agent_harness.toolkits.web_search.coalescing.search_cache_governor import (
    SearchCacheGovernor,
)
from myrm_agent_harness.toolkits.web_search.core.common import SearchResult


def _make_dummy_results(query: str, count: int = 2) -> list[SearchResult]:
    return [
        SearchResult(
            title=f"Result {i} for {query}",
            link=f"https://example.com/{query}/{i}",
            snippet=f"Snippet for {query} item {i}",
        )
        for i in range(count)
    ]


def test_query_freshness_detector_tier_classification() -> None:
    """Verifies that query text and prompt hints correctly map to freshness tiers."""
    detector = QueryFreshnessDetector(
        config=FreshnessGovernorConfig(default_ttl_seconds=900, short_ttl_seconds=120)
    )

    # 1. Realtime keywords
    res_stock = detector.detect("英伟达今日股价行情")
    assert res_stock.tier == QueryFreshnessTier.REALTIME_BYPASS
    assert res_stock.is_bypass_cache is True
    assert "股价" in res_stock.matched_keywords

    # 2. Prompt bypass directive in query or hint
    res_prompt = detector.detect("人工智能开源进展", prompt_hint="不要用缓存，获取最新消息")
    assert res_prompt.tier == QueryFreshnessTier.REALTIME_BYPASS
    assert res_prompt.is_bypass_cache is True
    assert "不要用缓存" in res_prompt.matched_keywords

    # 3. Dynamic short TTL
    res_weather = detector.detect("今日上海实时气温与天气预报")
    assert res_weather.tier == QueryFreshnessTier.DYNAMIC_SHORT_TTL
    assert res_weather.is_bypass_cache is False
    assert res_weather.effective_ttl_seconds == 120

    # 4. Standard technical inquiry
    res_std = detector.detect("Python asyncio event loop 内部架构原理")
    assert res_std.tier == QueryFreshnessTier.STANDARD_TTL
    assert res_std.is_bypass_cache is False
    assert res_std.effective_ttl_seconds == 900


@pytest.mark.asyncio
async def test_standard_query_cache_hit_and_reuse() -> None:
    """Verifies that standard queries hit cache on subsequent requests."""
    governor = SearchCacheGovernor()
    governor.reset_state_for_tests()
    fetch_count = 0

    async def mock_fetch() -> list[SearchResult]:
        nonlocal fetch_count
        fetch_count += 1
        return _make_dummy_results("python_arch")

    # First call misses cache
    res1, r1 = await governor.execute_governed_search(
        search_service="mock_svc",
        query="python 核心技术规范",
        caller_limit=5,
        fetch=mock_fetch,
    )
    assert len(res1) == 2
    assert r1.cache_hit is False
    assert fetch_count == 1

    # Second call hits cache
    res2, r2 = await governor.execute_governed_search(
        search_service="mock_svc",
        query="python 核心技术规范",
        caller_limit=5,
        fetch=mock_fetch,
    )
    assert len(res2) == 2
    assert r2.cache_hit is True
    assert fetch_count == 1


@pytest.mark.asyncio
async def test_realtime_bypass_single_flight_stampede_protection() -> None:
    """Verifies that concurrent realtime bypass queries share one in-flight fetch without stampede."""
    governor = SearchCacheGovernor()
    governor.reset_state_for_tests()
    fetch_invocations = 0

    async def slow_realtime_fetch() -> list[SearchResult]:
        nonlocal fetch_invocations
        fetch_invocations += 1
        await asyncio.sleep(0.08)
        return _make_dummy_results("nvda_price")

    # Fire 5 concurrent requests for real-time stock price
    tasks = [
        governor.execute_governed_search(
            search_service="mock_svc",
            query="英伟达实时股价",
            caller_limit=5,
            fetch=slow_realtime_fetch,
        )
        for _ in range(5)
    ]

    results_and_receipts = await asyncio.gather(*tasks)

    # Exactly 1 fetch executed by the leader
    assert fetch_invocations == 1

    # All callers received data
    for res, rec in results_and_receipts:
        assert len(res) == 2
        assert rec.detection.is_bypass_cache is True
        assert rec.detection.tier == QueryFreshnessTier.REALTIME_BYPASS

    # Subsequent request is not cached because it is realtime bypass
    _res_after, rec_after = await governor.execute_governed_search(
        search_service="mock_svc",
        query="英伟达实时股价",
        caller_limit=5,
        fetch=slow_realtime_fetch,
    )
    assert rec_after.cache_hit is False
    assert fetch_invocations == 2


@pytest.mark.asyncio
async def test_dynamic_short_ttl_expiration() -> None:
    """Verifies that short-TTL entries expire after configured timeout."""
    cfg = FreshnessGovernorConfig(short_ttl_seconds=1)
    governor = SearchCacheGovernor(config=cfg)
    governor.reset_state_for_tests()
    fetch_counter = 0

    async def weather_fetch() -> list[SearchResult]:
        nonlocal fetch_counter
        fetch_counter += 1
        return _make_dummy_results("weather_forecast")

    # 1. Initial call populates short TTL cache
    _, r1 = await governor.execute_governed_search(
        search_service="mock_svc",
        query="今日天气预报",
        caller_limit=5,
        fetch=weather_fetch,
    )
    assert r1.cache_hit is False
    assert fetch_counter == 1

    # 2. Immediate repeat hits cache
    _, r2 = await governor.execute_governed_search(
        search_service="mock_svc",
        query="今日天气预报",
        caller_limit=5,
        fetch=weather_fetch,
    )
    assert r2.cache_hit is True
    assert fetch_counter == 1

    # 3. Simulate passage of time for 1s TTL
    await asyncio.sleep(1.05)

    # 4. Third call sees expired cache and refetches
    _, r3 = await governor.execute_governed_search(
        search_service="mock_svc",
        query="今日天气预报",
        caller_limit=5,
        fetch=weather_fetch,
    )
    assert r3.cache_hit is False
    assert fetch_counter == 2
