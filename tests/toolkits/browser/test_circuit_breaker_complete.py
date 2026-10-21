"""Complete coverage tests for CircuitBreaker - covers missing lines"""

import asyncio

import pytest

from myrm_agent_harness.toolkits.browser.pool.circuit_breaker import (
    CircuitBreaker,
    LoggingCallback,
)


@pytest.mark.asyncio
async def test_circuit_breaker_auto_recovery_with_callback(caplog):
    """测试：超时后自动恢复并触发 on_close 回调"""
    import logging

    breaker = CircuitBreaker(failure_threshold=2, timeout=0.5)

    async def fail_func() -> str:
        raise ValueError("failure")

    # 失败2次，熔断器打开
    with caplog.at_level(logging.WARNING):
        for _ in range(2):
            with pytest.raises(ValueError):
                await breaker.call("http://example.com", fail_func)

    # 验证打开日志
    assert "Circuit breaker OPENED" in caplog.text
    assert "example.com" in caplog.text
    assert breaker.get_state("http://example.com") == "OPEN"

    # 等待超时
    await asyncio.sleep(0.6)

    # 再次调用 get_state，触发自动恢复
    with caplog.at_level(logging.INFO):
        state = breaker.get_state("http://example.com")

    # 验证恢复日志（on_close 被调用）
    assert state == "CLOSED"
    assert "Circuit breaker CLOSED" in caplog.text
    assert "recovered" in caplog.text


def test_logging_callback_on_close_direct(caplog):
    """测试：LoggingCallback.on_close 直接调用"""
    import logging

    callback = LoggingCallback()

    with caplog.at_level(logging.INFO):
        callback.on_close("test-domain.com")

    assert "Circuit breaker CLOSED" in caplog.text
    assert "test-domain.com" in caplog.text


@pytest.mark.asyncio
async def test_circuit_breaker_success_resets_failures():
    """测试：成功调用重置失败计数"""
    breaker = CircuitBreaker(failure_threshold=3, timeout=1.0)

    async def fail_func() -> str:
        raise ValueError("failure")

    async def success_func() -> str:
        return "success"

    # 失败2次（未达阈值）
    for _ in range(2):
        with pytest.raises(ValueError):
            await breaker.call("http://example.com", fail_func)

    # 成功1次，重置失败计数
    result = await breaker.call("http://example.com", success_func)
    assert result == "success"

    # 失败计数应该已重置，需要再失败3次才能触发熔断
    for _ in range(2):
        with pytest.raises(ValueError):
            await breaker.call("http://example.com", fail_func)

    # 仍然应该是CLOSED
    assert breaker.get_state("http://example.com") == "CLOSED"

    # 再失败1次，达到阈值
    with pytest.raises(ValueError):
        await breaker.call("http://example.com", fail_func)

    assert breaker.get_state("http://example.com") == "OPEN"
