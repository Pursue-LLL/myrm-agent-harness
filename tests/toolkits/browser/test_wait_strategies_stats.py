"""Unit tests for wait strategy runtime statistics."""

import pytest

from myrm_agent_harness.toolkits.browser.wait_strategies import (
    WaitStrategy,
    get_wait_strategy_stats,
    reset_wait_strategy_stats,
    wait_for_page_ready,
)


def test_stats_initial_state():
    """验证统计初始状态."""
    reset_wait_strategy_stats()
    stats = get_wait_strategy_stats()

    assert stats["total_calls"] == 0
    assert stats["avg_elapsed_ms"] == 0
    assert stats["strategy_usage"] == {}


def test_stats_reset():
    """验证统计重置功能."""
    reset_wait_strategy_stats()

    # 模拟一些调用（通过内部API）
    from myrm_agent_harness.toolkits.browser.wait_strategies import _global_stats

    _global_stats.record_call(WaitStrategy.SMART, "network_only", 100)
    _global_stats.record_call(WaitStrategy.HYBRID, "both", 200)

    stats = get_wait_strategy_stats()
    assert stats["total_calls"] == 2

    # 重置
    reset_wait_strategy_stats()
    stats = get_wait_strategy_stats()
    assert stats["total_calls"] == 0


def test_stats_strategy_counting():
    """验证策略使用次数统计."""
    reset_wait_strategy_stats()

    from myrm_agent_harness.toolkits.browser.wait_strategies import _global_stats

    _global_stats.record_call(WaitStrategy.SMART, "network_only", 10)
    _global_stats.record_call(WaitStrategy.SMART, "network_only", 20)
    _global_stats.record_call(WaitStrategy.HYBRID, "both", 30)
    _global_stats.record_call(WaitStrategy.DOM_STABLE, "quiet", 40)

    stats = get_wait_strategy_stats()

    assert stats["total_calls"] == 4
    assert stats["strategy_usage"]["smart"] == 2
    assert stats["strategy_usage"]["hybrid"] == 1
    assert stats["strategy_usage"]["dom_stable"] == 1


def test_stats_smart_hit_rate():
    """验证SMART策略快速路径命中率统计."""
    reset_wait_strategy_stats()

    from myrm_agent_harness.toolkits.browser.wait_strategies import _global_stats

    # 3次快速路径命中
    _global_stats.record_call(WaitStrategy.SMART, "network_only", 10)
    _global_stats.record_call(WaitStrategy.SMART, "network_only", 15)
    _global_stats.record_call(WaitStrategy.SMART, "network_only", 12)

    # 1次降级
    _global_stats.record_call(WaitStrategy.SMART, "both", 200)

    stats = get_wait_strategy_stats()

    assert stats["smart_fast_path_hits"] == 3
    assert stats["smart_fast_path_misses"] == 1
    assert stats["smart_fast_path_hit_rate"] == 0.75  # 3/4


def test_stats_hybrid_both_rate():
    """验证HYBRID策略双完成率统计."""
    reset_wait_strategy_stats()

    from myrm_agent_harness.toolkits.browser.wait_strategies import _global_stats

    # 6次双完成
    for _ in range(6):
        _global_stats.record_call(WaitStrategy.HYBRID, "both", 100)

    # 4次单完成
    for _ in range(4):
        _global_stats.record_call(WaitStrategy.HYBRID, "first_completed", 150)

    stats = get_wait_strategy_stats()

    assert stats["hybrid_both_completed"] == 6
    assert stats["hybrid_first_completed"] == 4
    assert stats["hybrid_both_rate"] == 0.6  # 6/10


def test_stats_avg_elapsed_ms():
    """验证平均等待时长统计."""
    reset_wait_strategy_stats()

    from myrm_agent_harness.toolkits.browser.wait_strategies import _global_stats

    _global_stats.record_call(WaitStrategy.SMART, "network_only", 10)
    _global_stats.record_call(WaitStrategy.SMART, "network_only", 20)
    _global_stats.record_call(WaitStrategy.HYBRID, "both", 30)

    stats = get_wait_strategy_stats()

    assert stats["total_calls"] == 3
    assert stats["avg_elapsed_ms"] == 20.0  # (10+20+30)/3


@pytest.mark.asyncio
async def test_stats_integration_with_wait_for_page_ready():
    """验证wait_for_page_ready自动记录统计."""
    # 使用mock page简化测试，避免浏览器依赖
    from unittest.mock import AsyncMock, MagicMock

    reset_wait_strategy_stats()

    # 创建mock page
    mock_page = MagicMock()
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.evaluate = AsyncMock(
        return_value={
            "reason": "quiet",
            "elapsed_ms": 100,
            "mutation_count": 5,
            "reset_count": 2,
            "shadow_count": 0,
        }
    )

    # 调用wait_for_page_ready多次
    for _ in range(3):
        await wait_for_page_ready(
            mock_page,  # type: ignore
            strategy=WaitStrategy.DOM_STABLE,
            max_ms=3000,
        )

    # 检查统计
    stats = get_wait_strategy_stats()

    assert stats["total_calls"] == 3
    assert "dom_stable" in stats["strategy_usage"]
    assert stats["strategy_usage"]["dom_stable"] == 3
    assert stats["avg_elapsed_ms"] >= 0


def test_stats_thread_safety():
    """验证统计的线程安全性."""
    import concurrent.futures

    reset_wait_strategy_stats()

    from myrm_agent_harness.toolkits.browser.wait_strategies import _global_stats

    def record_many(count: int) -> None:
        for i in range(count):
            _global_stats.record_call(WaitStrategy.SMART, "network_only", i)

    # 10个线程，每个记录100次
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(record_many, 100) for _ in range(10)]
        concurrent.futures.wait(futures)

    stats = get_wait_strategy_stats()

    # 应该正好1000次
    assert stats["total_calls"] == 1000
    assert stats["smart_fast_path_hits"] == 1000
