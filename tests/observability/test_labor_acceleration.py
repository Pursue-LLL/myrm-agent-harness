"""
[INPUT]
- myrm_agent_harness.observability.labor_acceleration::{
    LaborAccelerationCalculator,
    LaborAccelerationSummary,
    LaborEquivalencyItem,
    TaskActionType,
  }

[OUTPUT]
- 白领劳务效能加速度量化与生产力 ROI 单元测试

[POS]
myrm-agent-harness/tests/observability/test_labor_acceleration.py — 劳务工时等效换算单测。
"""

import pytest
from myrm_agent_harness.observability.labor_acceleration import (
    LaborAccelerationCalculator,
    LaborAccelerationSummary,
    LaborEquivalencyItem,
    TaskActionType,
)


def test_labor_acceleration_models_serialization() -> None:
    item = LaborEquivalencyItem(
        action_type=TaskActionType.WEB_RESEARCH,
        label="多信源深度搜索与交叉比对",
        count=5,
        hours_per_unit=0.10,
        total_hours_saved=0.50,
    )
    data = item.to_dict()
    assert data["action_type"] == "web_research"
    assert data["count"] == 5
    assert data["hours_per_unit"] == 0.10
    assert data["total_hours_saved"] == 0.50

    summary = LaborAccelerationSummary(
        task_id="task-hermes-labor-1",
        task_elapsed_seconds=45.0,
        total_hours_saved=1.2,
        acceleration_factor=96.0,
        hourly_rate_usd=35.0,
        estimated_saved_value_usd=42.0,
        compute_cost_usd=0.05,
        roi_ratio=840.0,
        breakdown=[item],
    )
    s_dict = summary.to_dict()
    assert s_dict["task_id"] == "task-hermes-labor-1"
    assert s_dict["acceleration_factor"] == 96.0
    assert s_dict["estimated_saved_value_usd"] == 42.0
    assert s_dict["roi_ratio"] == 840.0
    assert len(s_dict["breakdown"]) == 1


def test_labor_acceleration_calculator_task_flow() -> None:
    calculator = LaborAccelerationCalculator()

    # 模拟真实白领复杂任务：用时 45 秒完成 4 次网络研究 + 2 份长文提取 + 1 轮代码沙箱闭环
    action_counts = {
        TaskActionType.WEB_RESEARCH: 4,     # 4 * 0.10 = 0.40h
        TaskActionType.DOC_EXTRACTION: 2,   # 2 * 0.25 = 0.50h
        TaskActionType.CODE_EXECUTION: 1,   # 1 * 0.3333 = 0.3333h
    }

    summary = calculator.calculate_task_summary(
        task_id="task-white-collar-001",
        task_elapsed_seconds=45.0,
        action_counts=action_counts,
        compute_cost_usd=0.05,
        hourly_rate_usd=40.0,
    )

    assert summary.task_id == "task-white-collar-001"
    assert summary.task_elapsed_seconds == 45.0
    # 总工时 ≈ 0.40 + 0.50 + 0.3333 = 1.2333 小时
    assert 1.23 < summary.total_hours_saved < 1.24
    # 加速倍率: (1.2333 * 3600) / 45 ≈ 98.66×
    assert 95.0 < summary.acceleration_factor < 102.0
    # 挽回人工商业价值: 1.2333 * $40.0 ≈ $49.33
    assert 49.0 < summary.estimated_saved_value_usd < 50.0
    # 投入产出比: 49.33 / 0.05 ≈ 986.6×
    assert summary.roi_ratio > 900.0
    assert len(summary.breakdown) == 3


def test_labor_acceleration_calculator_boundary_zero_handling() -> None:
    calculator = LaborAccelerationCalculator()

    # 无行为或 0 秒极限场景
    summary = calculator.calculate_task_summary(
        task_id="task-empty",
        task_elapsed_seconds=0.0,
        action_counts={},
        compute_cost_usd=0.0,
    )

    assert summary.task_id == "task-empty"
    assert summary.total_hours_saved == 0.0
    assert summary.acceleration_factor == 0.0
    assert summary.roi_ratio == 0.0
    assert summary.breakdown == []
