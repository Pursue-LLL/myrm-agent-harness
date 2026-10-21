"""
Unit tests for Cumulative Delivery Budget & Unknown Usage Audit Ledger.
Tests dual-ledger accounting, conservative imputation for unmetered calls, and hard budget fuses.
"""

from myrm_agent_harness.observability.cumulative_delivery_budget import (
    CumulativeDeliveryLedgerManager,
    DeliveryBudgetGate,
    UnknownUsageStatus,
)


def test_metered_trials_and_dual_ledger_aggregation() -> None:
    manager = CumulativeDeliveryLedgerManager()
    ledger = manager.create_or_get_ledger(
        delivery_id="delivery-task-01",
        title="企业级全库知识图谱构建",
        budget_tokens_limit=50000,
        budget_cost_limit_usd=0.50,
    )

    # 1. 记录初始规划阶段 Trial
    manager.record_trial(
        delivery_id="delivery-task-01",
        trial_id="trial-plan-01",
        agent_id="agent-planner",
        agent_role="planner",
        attempt_index=1,
        step_name="拆解全局文档依赖图",
        prompt_tokens=2000,
        completion_tokens=600,
        cost_usd=0.012,
        latency_ms=1200.0,
    )

    # 2. 记录 Worker 抽取阶段 Trial
    manager.record_trial(
        delivery_id="delivery-task-01",
        trial_id="trial-worker-02",
        agent_id="agent-coder-01",
        agent_role="worker",
        attempt_index=1,
        step_name="批量提取实体属性",
        prompt_tokens=4000,
        completion_tokens=1500,
        cost_usd=0.035,
        latency_ms=2500.0,
    )

    updated = manager.get_ledger("delivery-task-01")
    assert updated is not None
    assert updated.total_trials_count == 2
    assert updated.unmetered_trials_count == 0
    assert updated.total_metered_tokens == 8100
    assert updated.total_effective_tokens == 8100
    assert updated.total_metered_cost_usd == 0.047
    assert updated.gate_verdict == DeliveryBudgetGate.NORMAL
    assert not updated.is_paused


def test_explicit_unknown_usage_auditing_and_imputation() -> None:
    manager = CumulativeDeliveryLedgerManager(
        default_imputed_prompt_tokens=1500,
        default_imputed_completion_tokens=500,
        default_imputed_cost_usd=0.006,
    )
    manager.create_or_get_ledger(delivery_id="delivery-task-02", title="海量爬虫流水线")

    # 1. 记录显式未计量调用 (例如流式断开无 usage 字段)
    manager.record_trial(
        delivery_id="delivery-task-02",
        trial_id="trial-crawler-01",
        agent_id="agent-crawler",
        agent_role="worker",
        attempt_index=1,
        step_name="异步解析外部表格",
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=0.0,
        is_unmetered=True,
        unmetered_status=UnknownUsageStatus.UNMETERED_PROVIDER_EMPTY,
    )

    # 2. 记录超时隐式未计量调用 (tokens 均为 0 且 status 为 timeout)
    manager.record_trial(
        delivery_id="delivery-task-02",
        trial_id="trial-crawler-02",
        agent_id="agent-crawler",
        agent_role="worker",
        attempt_index=2,
        step_name="重试解析外部表格",
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=0.0,
        status="timeout",
    )

    ledger = manager.get_ledger("delivery-task-02")
    assert ledger is not None
    assert ledger.total_trials_count == 2
    assert ledger.unmetered_trials_count == 2
    assert ledger.total_metered_tokens == 0
    # 每笔计提 1500 + 500 = 2000 tokens，两笔共 4000 tokens
    assert ledger.total_imputed_tokens == 4000
    assert ledger.total_effective_tokens == 4000
    assert ledger.total_imputed_cost_usd == 0.012
    assert ledger.total_effective_cost_usd == 0.012

    trials = ledger.trials
    assert trials[0].is_unmetered
    assert trials[0].unmetered_status == UnknownUsageStatus.UNMETERED_PROVIDER_EMPTY
    assert trials[1].is_unmetered
    assert trials[1].unmetered_status == UnknownUsageStatus.UNMETERED_TIMEOUT


def test_budget_gate_ladder_and_hard_pause_fuse() -> None:
    manager = CumulativeDeliveryLedgerManager()
    manager.create_or_get_ledger(
        delivery_id="delivery-task-03",
        title="长程智能体测试",
        budget_tokens_limit=10000,
        budget_cost_limit_usd=0.10,
    )

    # 1. 消耗 6000 tokens (60%) -> NORMAL
    manager.record_trial(
        delivery_id="delivery-task-03",
        trial_id="trial-1",
        agent_id="agent-worker",
        agent_role="coder",
        attempt_index=1,
        step_name="生成前端代码",
        prompt_tokens=5000,
        completion_tokens=1000,
        cost_usd=0.03,
    )
    ledger = manager.get_ledger("delivery-task-03")
    assert ledger.gate_verdict == DeliveryBudgetGate.NORMAL
    assert not ledger.is_paused

    # 2. 消耗追加 2000 tokens (达到 8000 / 10000 = 80%) -> WARNING_70
    manager.record_trial(
        delivery_id="delivery-task-03",
        trial_id="trial-2",
        agent_id="agent-worker",
        agent_role="coder",
        attempt_index=2,
        step_name="编写集成测试",
        prompt_tokens=1500,
        completion_tokens=500,
        cost_usd=0.02,
    )
    ledger = manager.get_ledger("delivery-task-03")
    assert ledger.gate_verdict == DeliveryBudgetGate.WARNING_70
    assert not ledger.is_paused

    # 3. 消耗追加 2500 tokens (达到 10500 / 10000 = 105%) -> EXCEEDED_PAUSED_100 硬熔断
    manager.record_trial(
        delivery_id="delivery-task-03",
        trial_id="trial-3",
        agent_id="agent-worker",
        agent_role="coder",
        attempt_index=3,
        step_name="补充单测用例",
        prompt_tokens=2000,
        completion_tokens=500,
        cost_usd=0.02,
    )
    ledger = manager.get_ledger("delivery-task-03")
    assert ledger.gate_verdict == DeliveryBudgetGate.EXCEEDED_PAUSED_100
    assert ledger.is_paused
    assert "触发保护性熔断挂起" in (ledger.pause_reason or "")

    # 4. 人工追加 5000 tokens 预算并解除挂起
    resumed_ledger = manager.append_budget(
        delivery_id="delivery-task-03",
        additional_tokens=5000,
        force_unpause=True,
    )
    assert resumed_ledger.budget_tokens_limit == 15000
    assert not resumed_ledger.is_paused
    # 10500 / 15000 = 70.0% -> WARNING_70
    assert resumed_ledger.gate_verdict == DeliveryBudgetGate.WARNING_70
