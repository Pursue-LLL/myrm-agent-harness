"""Unit tests for CircuitBreaker"""

import pytest

from myrm_agent_harness.toolkits.browser.pool.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
)


@pytest.mark.asyncio
async def test_circuit_breaker_closed_state():
    """测试：正常状态下熔断器允许请求通过"""
    breaker = CircuitBreaker(failure_threshold=3, timeout=1.0)

    async def success_func() -> str:
        return "success"

    result = await breaker.call("http://example.com", success_func)
    assert result == "success"
    assert breaker.get_state("http://example.com") == "CLOSED"


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_failures():
    """测试：连续失败达到阈值后熔断器打开"""
    breaker = CircuitBreaker(failure_threshold=3, timeout=1.0)

    async def fail_func() -> str:
        raise ValueError("simulated failure")

    # 连续失败3次
    for _ in range(3):
        with pytest.raises(ValueError):
            await breaker.call("http://example.com", fail_func)

    # 熔断器应该打开
    assert breaker.get_state("http://example.com") == "OPEN"

    # 下一次请求应该被拒绝
    with pytest.raises(CircuitBreakerOpenError):
        await breaker.call("http://example.com", fail_func)


@pytest.mark.asyncio
async def test_circuit_breaker_domain_isolation():
    """测试：不同域名的熔断器独立"""
    breaker = CircuitBreaker(failure_threshold=2, timeout=1.0)

    async def fail_func() -> str:
        raise ValueError("failure")

    # domain1 失败2次
    for _ in range(2):
        with pytest.raises(ValueError):
            await breaker.call("http://domain1.com", fail_func)

    assert breaker.get_state("http://domain1.com") == "OPEN"

    # domain2 应该仍然正常
    async def success_func() -> str:
        return "success"

    result = await breaker.call("http://domain2.com", success_func)
    assert result == "success"
    assert breaker.get_state("http://domain2.com") == "CLOSED"


@pytest.mark.asyncio
async def test_circuit_breaker_reset():
    """测试：重置熔断器"""
    breaker = CircuitBreaker(failure_threshold=2, timeout=1.0)

    async def fail_func() -> str:
        raise ValueError("failure")

    # 失败2次，熔断器打开
    for _ in range(2):
        with pytest.raises(ValueError):
            await breaker.call("http://example.com", fail_func)

    assert breaker.get_state("http://example.com") == "OPEN"

    # 重置
    breaker.reset("http://example.com")
    assert breaker.get_state("http://example.com") == "CLOSED"


@pytest.mark.asyncio
async def test_circuit_breaker_stats():
    """测试：熔断器统计信息"""
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

    stats = breaker.stats
    assert stats["open_circuits"] == 1
    assert stats["domains_with_failures"] == 1
    assert "domain1.com" in stats["open_domains"]
