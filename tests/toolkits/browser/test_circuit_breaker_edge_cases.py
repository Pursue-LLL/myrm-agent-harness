"""Edge case tests for CircuitBreaker to achieve 100% coverage"""

import pytest

from myrm_agent_harness.toolkits.browser.pool.circuit_breaker import CircuitBreaker


@pytest.mark.asyncio
async def test_circuit_breaker_reset_all():
    """测试：重置所有域名的熔断器"""
    breaker = CircuitBreaker(failure_threshold=2, timeout=1.0)

    async def fail_func() -> str:
        raise ValueError("failure")

    # domain1 失败2次
    for _ in range(2):
        with pytest.raises(ValueError):
            await breaker.call("http://domain1.com", fail_func)

    # domain2 失败1次
    with pytest.raises(ValueError):
        await breaker.call("http://domain2.com", fail_func)

    # 验证状态
    assert breaker.get_state("http://domain1.com") == "OPEN"
    assert breaker.get_state("http://domain2.com") == "CLOSED"

    # 重置所有（url=None）
    breaker.reset(None)

    # 验证所有域名都已重置
    assert breaker.get_state("http://domain1.com") == "CLOSED"
    assert breaker.get_state("http://domain2.com") == "CLOSED"
    assert len(breaker._failure_counts) == 0
    assert len(breaker._open_until) == 0


def test_circuit_breaker_extract_domain_fallback():
    """测试：URL解析失败时fallback到原URL"""
    breaker = CircuitBreaker()

    # 无法解析的URL（没有netloc）
    domain = breaker._extract_domain("not-a-valid-url")
    assert domain == "not-a-valid-url"


@pytest.mark.asyncio
async def test_circuit_breaker_stats_open_until():
    """测试：stats包含open_until剩余时间"""
    import asyncio

    breaker = CircuitBreaker(failure_threshold=2, timeout=1.0)

    async def fail_func() -> str:
        raise ValueError("failure")

    # 失败2次，熔断器打开
    for _ in range(2):
        with pytest.raises(ValueError):
            await breaker.call("http://example.com", fail_func)

    stats = breaker.stats
    assert "open_until" in stats
    assert "example.com" in stats["open_until"]
    assert stats["open_until"]["example.com"] > 0  # 剩余时间>0

    # 等待超时
    await asyncio.sleep(1.1)

    # 剩余时间应该<=0（不再在open_until中）
    stats = breaker.stats
    assert len(stats["open_until"]) == 0
