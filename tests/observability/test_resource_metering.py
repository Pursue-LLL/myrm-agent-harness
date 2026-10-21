"""
[INPUT]
- myrm_agent_harness.observability.resource_metering::{
    BudgetCircuitBreaker,
    CognitiveUsage,
    HardwareUsage,
    HybridLedgerReport,
    ResourceMeteringLedger,
  }

[OUTPUT]
- 混合算力计量与全景对账单单元测试

[POS]
myrm-agent-harness/tests/observability/test_resource_metering.py — 资源计量对账单与预算熔断单测。
"""

import pytest
from myrm_agent_harness.observability.resource_metering import (
    BudgetCircuitBreaker,
    CognitiveUsage,
    HardwareUsage,
    HybridLedgerReport,
    ResourceMeteringLedger,
)


def test_resource_metering_models_serialization() -> None:
    hw = HardwareUsage(
        execution_seconds=660.0,
        cpu_cores=2.0,
        memory_gb=4.0,
        volume_read_mb=50.0,
        volume_write_mb=25.0,
        hardware_credits=11.46,
    )
    hw_dict = hw.to_dict()
    assert hw_dict["execution_seconds"] == 660.0
    assert hw_dict["cpu_cores"] == 2.0
    assert hw_dict["hardware_credits"] == 11.46

    cog = CognitiveUsage(
        model_name="deepseek-v3",
        prompt_tokens=100000,
        completion_tokens=20000,
        cached_prompt_tokens=50000,
        cognitive_credits=55.0,
    )
    cog_dict = cog.to_dict()
    assert cog_dict["model_name"] == "deepseek-v3"
    assert cog_dict["prompt_tokens"] == 100000
    assert cog_dict["cached_prompt_tokens"] == 50000
    assert cog_dict["cognitive_credits"] == 55.0


def test_resource_metering_ledger_calculations() -> None:
    ledger = ResourceMeteringLedger()

    # 1. 模拟 11 分钟 (660 秒) 2C/4G 沙箱任务（对标火山方舟官方 Demo）
    hw = HardwareUsage(
        execution_seconds=660.0,
        cpu_cores=2.0,
        memory_gb=4.0,
        volume_read_mb=100.0,
        volume_write_mb=50.0,
    )
    hw_credits = ledger.calculate_hardware_credits(hw)
    # 660 * 0.017361 = 11.45826 + IO 0.015 ≈ 11.473
    assert 11.4 < hw_credits < 11.55

    # 2. 认知 Token 折算
    cog = CognitiveUsage(
        model_name="deepseek-v3",
        prompt_tokens=20000,        # 20k
        completion_tokens=5000,      # 5k
        cached_prompt_tokens=10000,  # 10k 缓存
    )
    cog_credits = ledger.calculate_cognitive_credits(cog)
    # non_cached 10k * 0.50 = 5.0
    # cached 10k * 0.10 = 1.0
    # completion 5k * 1.50 = 7.5
    # total = 13.5
    assert abs(cog_credits - 13.5) < 0.001

    # 3. 生成完整报告
    report = ledger.generate_task_report(
        task_id="task-cloud-metering-001",
        hardware=hw,
        cognitive=cog,
    )
    assert report.task_id == "task-cloud-metering-001"
    assert abs(report.total_credits - (hw_credits + 13.5)) < 0.001
    assert report.estimated_cost_usd > 0.0
    assert report.is_budget_exceeded is False


def test_budget_circuit_breaker_triggers() -> None:
    ledger = ResourceMeteringLedger()

    # 设置预算阈值：最大 600 秒，最大 15000 Tokens，最大 20 Credits
    breaker = BudgetCircuitBreaker(
        max_execution_seconds=600.0,
        max_total_tokens=15000,
        max_total_credits=20.0,
    )

    # 场景 1：超时熔断
    hw_overtime = HardwareUsage(execution_seconds=700.0)
    cog_normal = CognitiveUsage(prompt_tokens=1000, completion_tokens=500)
    report1 = ledger.generate_task_report("task-1", hw_overtime, cog_normal, circuit_breaker=breaker)
    assert report1.is_budget_exceeded is True
    assert "物理沙箱运行时间" in report1.budget_exceeded_reason

    # 场景 2：Token 预算熔断
    hw_normal = HardwareUsage(execution_seconds=100.0)
    cog_overtoken = CognitiveUsage(prompt_tokens=12000, completion_tokens=4000)  # 总 16k > 15k
    report2 = ledger.generate_task_report("task-2", hw_normal, cog_overtoken, circuit_breaker=breaker)
    assert report2.is_budget_exceeded is True
    assert "认知 Token 消耗总数" in report2.budget_exceeded_reason

    # 场景 3：总积分超限熔断
    cog_heavy = CognitiveUsage(prompt_tokens=8000, completion_tokens=15000)
    breaker_credits = BudgetCircuitBreaker(max_total_credits=10.0)
    report3 = ledger.generate_task_report("task-3", hw_normal, cog_heavy, circuit_breaker=breaker_credits)
    assert report3.is_budget_exceeded is True
    assert "综合算力积分总消耗" in report3.budget_exceeded_reason
