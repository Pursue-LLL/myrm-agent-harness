"""Tests for P2 optimization: CircuitBreaker callback support"""

import pytest

from myrm_agent_harness.toolkits.browser.pool.circuit_breaker import (
    CircuitBreaker,
)


class CallbackSpy:
    """回调spy，用于测试"""

    def __init__(self):
        self.on_open_calls: list[tuple[str, int]] = []
        self.on_close_calls: list[str] = []

    def on_open(self, domain: str, failure_count: int) -> None:
        self.on_open_calls.append((domain, failure_count))

    def on_close(self, domain: str) -> None:
        self.on_close_calls.append(domain)


@pytest.mark.asyncio
async def test_circuit_breaker_default_callback(caplog):
    """测试：默认使用LoggingCallback"""
    import logging

    breaker = CircuitBreaker(failure_threshold=2, timeout=1.0)

    async def fail_func() -> str:
        raise ValueError("failure")

    with caplog.at_level(logging.WARNING):
        # 失败2次，触发熔断
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call("http://example.com", fail_func)

    # 验证日志中包含回调记录
    assert "Circuit breaker OPENED" in caplog.text
    assert "example.com" in caplog.text


@pytest.mark.asyncio
async def test_circuit_breaker_on_open_callback():
    """测试：熔断器打开时触发on_open回调"""
    spy = CallbackSpy()
    breaker = CircuitBreaker(failure_threshold=3, timeout=1.0, callback=spy)

    async def fail_func() -> str:
        raise ValueError("failure")

    # 失败3次，触发熔断
    for _ in range(3):
        with pytest.raises(ValueError):
            await breaker.call("http://example.com", fail_func)

    # 验证on_open被调用
    assert len(spy.on_open_calls) == 1
    assert spy.on_open_calls[0] == ("example.com", 3)


@pytest.mark.asyncio
async def test_circuit_breaker_multi_domain_callbacks():
    """测试：多域名各自触发回调"""
    spy = CallbackSpy()
    breaker = CircuitBreaker(failure_threshold=2, timeout=1.0, callback=spy)

    async def fail_func() -> str:
        raise ValueError("failure")

    # domain1 失败2次
    for _ in range(2):
        with pytest.raises(ValueError):
            await breaker.call("http://domain1.com", fail_func)

    # domain2 失败2次
    for _ in range(2):
        with pytest.raises(ValueError):
            await breaker.call("http://domain2.com", fail_func)

    # 验证on_open被调用2次（domain1和domain2各1次）
    assert len(spy.on_open_calls) == 2
    assert ("domain1.com", 2) in spy.on_open_calls
    assert ("domain2.com", 2) in spy.on_open_calls
