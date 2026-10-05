"""Unit tests for Future Action Impact Filtering Gate and Extraction Admission."""

import pytest

from myrm_agent_harness.toolkits.memory.action_impact import (
    ActionImpactCategory,
    ActionImpactFilteringGate,
    ActionImpactTier,
    FutureActionImpactEvaluator,
)


@pytest.fixture
def evaluator() -> FutureActionImpactEvaluator:
    """Fixture providing action impact evaluator."""
    return FutureActionImpactEvaluator()


@pytest.fixture
def gate(evaluator: FutureActionImpactEvaluator) -> ActionImpactFilteringGate:
    """Fixture providing filtering gate."""
    return ActionImpactFilteringGate(evaluator)


def test_policy_and_preference_persistence(evaluator: FutureActionImpactEvaluator) -> None:
    """Test explicit constraints and engineering preferences qualify for long-term persistence."""
    facts = [
        "团队规范：代码严禁使用 Any 类型，必须包含显式 Type Hints。",
        "架构原则：单个文件原则上不能超过 400 行，切勿堆砌冗余逻辑。",
        "Security rule: Always enforce zero-trust authentication across internal endpoints.",
    ]
    for f in facts:
        res = evaluator.evaluate_fact(f)
        assert res.category == ActionImpactCategory.CORE_PREFERENCE_OR_POLICY
        assert res.impact_score >= 0.80
        assert res.assigned_tier == ActionImpactTier.TIER_LONG_TERM_PERSIST
        assert res.will_alter_future_actions is True


def test_engineering_decision_persistence(evaluator: FutureActionImpactEvaluator) -> None:
    """Test durable architectural and infrastructure choices qualify for persistence."""
    facts = [
        "数据库采用 PostgreSQL 16 并且部署在 AWS us-west-2 区域。",
        "服务运行在端口 8080，对外暴露 gRPC 与 REST 双协议。",
        "Production database schema defines a users table with partitioned event ledgers.",
    ]
    for f in facts:
        res = evaluator.evaluate_fact(f)
        assert res.category == ActionImpactCategory.ENGINEERING_FACT_OR_DECISION
        assert res.impact_score >= 0.80
        assert res.assigned_tier == ActionImpactTier.TIER_LONG_TERM_PERSIST
        assert res.will_alter_future_actions is True


def test_ephemeral_task_state_buffering(evaluator: FutureActionImpactEvaluator) -> None:
    """Test transient task status notes route to ephemeral session buffer."""
    facts = [
        "当前正在排查第3个单测失败原因，暂时修改了 pytest 配置。",
        "第2步依赖下载完毕，稍后执行容器打包。",
        "Currently troubleshooting memory leak in worker thread; inspect logs shortly.",
    ]
    for f in facts:
        res = evaluator.evaluate_fact(f)
        assert res.category == ActionImpactCategory.EPHEMERAL_TASK_STATE
        assert 0.40 <= res.impact_score < 0.80
        assert res.assigned_tier == ActionImpactTier.TIER_SESSION_BUFFER
        assert res.will_alter_future_actions is False


def test_chitchat_and_speculation_discard(evaluator: FutureActionImpactEvaluator) -> None:
    """Test greetings, speculation, and chitchat are immediately discarded."""
    facts = [
        "你好啊，今天天气真不错！",
        "今天调试有点累了，哈哈。",
        "可能吧，或许试试看也行，随便了。",
        "Good morning! Just dropping in to say hi.",
        "Whatever, maybe it works.",
    ]
    for f in facts:
        res = evaluator.evaluate_fact(f)
        assert res.category == ActionImpactCategory.CHITCHAT_OR_SPECULATION
        assert res.impact_score < 0.40
        assert res.assigned_tier == ActionImpactTier.TIER_IMMEDIATE_DISCARD
        assert res.will_alter_future_actions is False


def test_gate_filter_and_route(gate: ActionImpactFilteringGate) -> None:
    """Test 3-tier partitioning of mixed candidate batch."""
    mixed_candidates = [
        "架构策略：严禁向后兼容坏代码，优先重构。",  # Persist
        "数据库采用 ClickHouse 进行日志聚合分析。",  # Persist
        "当前正在跑 benchmark 测试脚本。",  # Buffer
        "你好呀，今天吃饭了吗？",  # Discard
        "哈哈，这可真有意思。",  # Discard
    ]
    persisted, buffered, discarded = gate.filter_and_route(mixed_candidates)

    assert len(persisted) == 2
    assert len(buffered) == 1
    assert len(discarded) == 2

    assert all(p.assigned_tier == ActionImpactTier.TIER_LONG_TERM_PERSIST for p in persisted)
    assert all(b.assigned_tier == ActionImpactTier.TIER_SESSION_BUFFER for b in buffered)
    assert all(d.assigned_tier == ActionImpactTier.TIER_IMMEDIATE_DISCARD for d in discarded)


def test_gate_evaluate_batch_and_noise_reduction(gate: ActionImpactFilteringGate) -> None:
    """Test batch evaluation guarantees >= 80% noise reduction in noisy conversation."""
    candidates = [
        "核心决策：后端接口必须采用 Pydantic v2 进行强类型校验。",  # 1 Persist
        "你好！",  # 2 Discard
        "哈哈",  # 3 Discard
        "今天有点困。",  # 4 Discard
        "可能需要重启吧，随便试下。",  # 5 Discard
        "当前正在查看 stderr 输出。",  # 6 Buffer
        "早上好啊！",  # 7 Discard
        "这个方案或许行得通。",  # 8 Discard
        "先这样吧，不纠结了。",  # 9 Discard
        "排查发现临时日志文件比较大。",  # 10 Buffer
    ]
    persisted, summary = gate.evaluate_batch(candidates)

    assert len(persisted) == 1
    assert summary.total_candidates == 10
    assert summary.persisted_count == 1
    assert summary.session_buffered_count == 2
    assert summary.discarded_count == 7
    # Noise reduction = (2 + 7) / 10 = 90% (>= 80% requirement)
    assert summary.noise_reduction_ratio >= 0.80
    assert gate.cumulative_noise_reduction_ratio >= 0.80


def test_empty_batch_handling(gate: ActionImpactFilteringGate) -> None:
    """Test empty batch handling fallback."""
    persisted, summary = gate.evaluate_batch([])
    assert len(persisted) == 0
    assert summary.total_candidates == 0
    assert summary.noise_reduction_ratio == 1.0
