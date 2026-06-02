"""Unit tests for wait strategy parameter validation and edge cases."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.wait_strategies import (
    WaitStrategy,
    wait_for_page_ready,
)


def test_max_ms_validation_negative():
    """验证max_ms不能为负数."""

    async def test():
        mock_page = MagicMock()
        with pytest.raises(ValueError, match="max_ms must be positive"):
            await wait_for_page_ready(mock_page, max_ms=-1)

    asyncio.run(test())


def test_max_ms_validation_zero():
    """验证max_ms不能为0."""

    async def test():
        mock_page = MagicMock()
        with pytest.raises(ValueError, match="max_ms must be positive"):
            await wait_for_page_ready(mock_page, max_ms=0)

    asyncio.run(test())


def test_quiet_ms_validation_negative():
    """验证quiet_ms不能为负数."""

    async def test():
        mock_page = MagicMock()
        with pytest.raises(ValueError, match="quiet_ms must be non-negative"):
            await wait_for_page_ready(mock_page, quiet_ms=-1)

    asyncio.run(test())


def test_grace_period_ms_validation_negative():
    """验证grace_period_ms不能为负数."""

    async def test():
        mock_page = MagicMock()
        with pytest.raises(ValueError, match="grace_period_ms must be non-negative"):
            await wait_for_page_ready(mock_page, grace_period_ms=-1)

    asyncio.run(test())


@pytest.mark.asyncio
async def test_quiet_ms_auto_adjustment():
    """验证quiet_ms超过max_ms时自动调整."""
    from unittest.mock import patch

    mock_page = MagicMock()
    mock_page.wait_for_load_state = AsyncMock()

    # quiet_ms=1000 > max_ms=500，应该被调整为500
    with patch("myrm_agent_harness.toolkits.browser.wait_strategies.logger") as mock_logger:
        await wait_for_page_ready(
            mock_page,
            strategy=WaitStrategy.NETWORKIDLE,
            max_ms=500,
            quiet_ms=1000,
        )

        # 验证有警告日志
        mock_logger.warning.assert_called_once()
        assert "exceeds max_ms" in str(mock_logger.warning.call_args)


@pytest.mark.asyncio
async def test_task_cancellation_cleanup():
    """验证Task取消后正确清理."""
    mock_page = MagicMock()

    # 模拟一个永远不会完成的evaluate（用于测试取消）
    async def never_complete(*args, **kwargs):
        await asyncio.sleep(999)
        return {"reason": "quiet", "elapsed_ms": 0}

    mock_page.evaluate = never_complete
    mock_page.wait_for_load_state = AsyncMock(return_value=None)  # 快速完成

    # 使用hybrid策略，grace_period=50ms
    # network_task会快速完成，dom_task会在grace period后被取消
    metrics = await wait_for_page_ready(
        mock_page,
        strategy=WaitStrategy.HYBRID,
        max_ms=5000,
        grace_period_ms=50,
    )

    # 验证：应该返回first_completed（因为dom task被取消）
    assert metrics.reason in ("first_completed", "network_only")

    # 等待所有task完成（确保没有ResourceWarning）
    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_stats_precision_with_float():
    """验证统计精度（使用float存储）."""
    from myrm_agent_harness.toolkits.browser.wait_strategies import (
        _global_stats,
        reset_wait_strategy_stats,
    )

    reset_wait_strategy_stats()

    # 记录一些小数时间
    _global_stats.record_call(WaitStrategy.SMART, "network_only", 10)
    _global_stats.record_call(WaitStrategy.SMART, "network_only", 11)
    _global_stats.record_call(WaitStrategy.SMART, "network_only", 12)

    stats = _global_stats.get_stats()

    # 平均应该是 (10+11+12)/3 = 11.0（精确）
    assert stats["avg_elapsed_ms"] == 11.0
    assert stats["total_calls"] == 3

    # 继续累加
    _global_stats.record_call(WaitStrategy.SMART, "network_only", 13)

    stats = _global_stats.get_stats()

    # 平均应该是 (10+11+12+13)/4 = 11.5（精确）
    assert stats["avg_elapsed_ms"] == 11.5
    assert stats["total_calls"] == 4


@pytest.mark.asyncio
async def test_extreme_timeout_values():
    """验证极端超时值的处理."""
    mock_page = MagicMock()
    mock_page.wait_for_load_state = AsyncMock()

    # 极小值（接近0但合法）
    metrics = await wait_for_page_ready(mock_page, strategy=WaitStrategy.NETWORKIDLE, max_ms=1)
    assert metrics.elapsed_ms >= 0

    # 极大值（确保不会溢出）
    metrics = await wait_for_page_ready(mock_page, strategy=WaitStrategy.NETWORKIDLE, max_ms=999999)
    assert metrics.elapsed_ms >= 0


@pytest.mark.asyncio
async def test_page_closed_scenario():
    """验证页面关闭场景的处理."""
    mock_page = MagicMock()

    # 模拟页面已关闭（抛出RuntimeError）
    mock_page.wait_for_load_state = AsyncMock(side_effect=RuntimeError("Page closed"))

    # 应该捕获异常并返回capped metrics
    metrics = await wait_for_page_ready(mock_page, strategy=WaitStrategy.NETWORKIDLE, max_ms=5000)

    assert metrics.strategy == WaitStrategy.NETWORKIDLE
    assert metrics.reason == "capped"
    assert metrics.elapsed_ms >= 0


@pytest.mark.asyncio
async def test_concurrent_stats_updates():
    """验证并发统计更新的正确性."""
    import concurrent.futures

    from myrm_agent_harness.toolkits.browser.wait_strategies import (
        _global_stats,
        reset_wait_strategy_stats,
    )

    reset_wait_strategy_stats()

    def record_batch(count: int):
        for i in range(count):
            _global_stats.record_call(WaitStrategy.SMART, "network_only", i % 100)

    # 10个线程，每个记录100次
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(record_batch, 100) for _ in range(10)]
        concurrent.futures.wait(futures)

    stats = _global_stats.get_stats()

    # 验证：应该正好1000次调用
    assert stats["total_calls"] == 1000
    assert stats["smart_fast_path_hits"] == 1000

    # 验证平均值合理
    assert 0 <= stats["avg_elapsed_ms"] <= 100
