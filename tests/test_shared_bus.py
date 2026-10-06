# [POS] myrm-agent-harness/tests/test_shared_bus.py
# [INPUT] MultiAgentSharedMemoryBus, NegativeDecisionLedger, SharedMemoryConcurrencyPool, ReinforcedDecayScorer
# [OUTPUT] 共享记忆总线、并发连接池与方案否决账本完整单元测试

"""跨 Agent 共享记忆总线、并发连接池与方案否决账本单元测试。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.memory.shared_bus import (
    ConcurrencyPoolConfig,
    DecisionVetoSeverity,
    MultiAgentSharedMemoryBus,
    NegativeDecisionEntry,
    NegativeDecisionLedger,
    ReinforcedDecayConfig,
    ReinforcedDecayScorer,
    SharedMemoryConcurrencyPool,
)


def test_negative_decision_ledger_veto_conflict() -> None:
    """测试方案否决专属账本的记录与前置硬冲突拦截。"""
    ledger = NegativeDecisionLedger()

    entry = NegativeDecisionEntry(
        decision_id="veto-001",
        decision_subject="使用 Redis 缓存向量",
        veto_reason="单机沙箱无需引入外部 Redis 守护进程，增加维护负担与故障点",
        alternative_chosen="采用内置 SQLite WAL + 内存 LRU 缓存",
        context_summary="在 2026 架构评审中被明确否决",
        severity=DecisionVetoSeverity.HARD_BLOCK,
        scope="global",
    )
    ledger.record_veto(entry)

    # 1. 命中否决主题
    result = ledger.check_veto_conflict("我们提议在本次重构中使用 Redis 缓存向量数据")
    assert result.is_blocked is True
    assert len(result.matched_entries) == 1
    assert "NEGATIVE DECISION GUARD" in result.guard_prompt_slice
    assert "采用内置 SQLite WAL" in result.rejection_summary

    # 2. 无关提案不拦截
    clean_result = ledger.check_veto_conflict("我们将编写一个标准的 Python 算法")
    assert clean_result.is_blocked is False
    assert len(clean_result.matched_entries) == 0

    # 3. 移除否决记录
    assert ledger.remove_veto("veto-001") is True
    post_check = ledger.check_veto_conflict("使用 Redis 缓存向量")
    assert post_check.is_blocked is False


def test_negative_decision_ledger_warning_severity() -> None:
    """测试 WARNING 级别的否决记录不直接 hard block，但附带警示提示。"""
    ledger = NegativeDecisionLedger()
    entry = NegativeDecisionEntry(
        decision_id="veto-002",
        decision_subject="重构引入 Cython 加速",
        veto_reason="编译链复杂，跨端分发成本高",
        alternative_chosen="优先纯 Python 优化与矢量化计算",
        severity=DecisionVetoSeverity.WARNING,
        scope="project",
    )
    ledger.record_veto(entry)

    result = ledger.check_veto_conflict("测试重构引入 Cython 加速性能", scope="project")
    assert result.is_blocked is False
    assert len(result.matched_entries) == 1
    assert "[强烈预警]" in result.guard_prompt_slice


@pytest.mark.asyncio
async def test_shared_memory_concurrency_pool_read_write() -> None:
    """测试多 Agent 并发连接池的读读并发与写通道互斥。"""
    config = ConcurrencyPoolConfig(
        max_concurrent_readers=4,
        max_concurrent_writers=1,
        acquire_timeout_seconds=2.0,
        enable_memory_guard=False,  # 测试基础并发
    )
    pool = SharedMemoryConcurrencyPool(config=config)

    # 读通道并发
    async def reader_task() -> None:
        async with pool.read_session():
            await asyncio.sleep(0.01)

    await asyncio.gather(reader_task(), reader_task(), reader_task())
    status = pool.get_status()
    assert status.active_readers == 0
    assert status.active_writers == 0

    # 写通道互斥
    async with pool.write_session():
        status_in_write = pool.get_status()
        assert status_in_write.active_writers == 1

    status_after = pool.get_status()
    assert status_after.active_writers == 0


@pytest.mark.asyncio
async def test_shared_memory_concurrency_pool_backpressure_trigger() -> None:
    """测试内存背压守卫在阈值过载时触发阻断限流保护。"""
    # 设置一个极低的水位阈值 (例如 0.0001 MB)，必然触发背压保护
    config = ConcurrencyPoolConfig(
        memory_rss_threshold_mb=0.00001,
        enable_memory_guard=True,
    )
    pool = SharedMemoryConcurrencyPool(config=config)

    with pytest.raises(RuntimeError, match="Memory backpressure triggered"):
        async with pool.read_session():
            pass


def test_reinforced_decay_scorer_math() -> None:
    """测试命中频次正向强化与时间半衰期衰减的评分数学特性。"""
    config = ReinforcedDecayConfig(
        base_weight=1.0,
        hit_reinforcement_alpha=0.5,
        half_life_days=10.0,
        min_score_floor=0.05,
    )
    scorer = ReinforcedDecayScorer(config=config)

    now = datetime.now(UTC)

    # 1. 新写入且 0 命中的记忆
    score_fresh, decay_fresh, reinf_fresh = scorer.compute_score(
        base_weight=1.0,
        hit_count=0,
        last_accessed_at=now.isoformat(),
        now=now,
    )
    assert abs(decay_fresh - 1.0) < 0.01
    assert abs(reinf_fresh - 1.0) < 0.01
    assert abs(score_fresh - 1.0) < 0.01

    # 2. 高频命中的记忆 (hits = 10) 强化提升
    score_high, _decay_high, reinf_high = scorer.compute_score(
        base_weight=1.0,
        hit_count=10,
        last_accessed_at=now.isoformat(),
        now=now,
    )
    assert reinf_high > 1.5
    assert score_high > score_fresh

    # 3. 经过 10 天 (恰好 1 个半衰期) 的衰减
    past_time = now - timedelta(days=10)
    score_decayed, decay_factor, _ = scorer.compute_score(
        base_weight=1.0,
        hit_count=0,
        last_accessed_at=past_time.isoformat(),
        now=now,
    )
    assert abs(decay_factor - 0.5) < 0.05
    assert abs(score_decayed - 0.5) < 0.05

    # 4. 条目排名
    items = [
        scorer.score_item("m1", "decayed", 1.0, 0, past_time.isoformat(), now),
        scorer.score_item("m2", "hot", 1.0, 10, now.isoformat(), now),
    ]
    ranked = scorer.rank_items(items)
    assert ranked[0].memory_id == "m2"
    assert ranked[1].memory_id == "m1"


def test_multi_agent_shared_memory_bus_end_to_end() -> None:
    """测试多 Agent 共享记忆协同总线端到端一体化。"""
    bus = MultiAgentSharedMemoryBus()

    # 否决记录与前置检查
    bus.record_veto(
        NegativeDecisionEntry(
            decision_id="v1",
            decision_subject="重构采用单体多进程 RPC",
            veto_reason="开销过大且难以调试",
            alternative_chosen="使用进程内异步总线",
        )
    )

    check_res = bus.check_proposal("建议采用单体多进程 RPC 方案")
    assert check_res.is_blocked is True
    assert len(bus.list_vetoes()) == 1

    # 自学习打分
    scored = bus.score_memory(
        memory_id="fact-1",
        content="核心架构原则",
        base_weight=1.5,
        hit_count=5,
    )
    assert scored.composite_score > 1.5

    # 状态探针
    status = bus.get_pool_status()
    assert status.active_readers == 0
    assert status.status_message in ("HEALTHY",) or "THROTTLED" in status.status_message
