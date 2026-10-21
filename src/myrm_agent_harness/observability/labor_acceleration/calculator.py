"""
[INPUT]
- .models::LaborAccelerationSummary, LaborEquivalencyItem, TaskActionType (POS: 效能数据模型)

[OUTPUT]
- LaborAccelerationCalculator: 劳务工时等效换算、加速倍率与 ROI 计算引擎

[POS]
myrm-agent-harness/src/myrm_agent_harness/observability/labor_acceleration/calculator.py — 白领劳务等效工时置换与效能加速计算引擎。
"""

from __future__ import annotations

from .models import LaborAccelerationSummary, LaborEquivalencyItem, TaskActionType

# 默认人工工时置换标准矩阵 (小时/单位)
DEFAULT_EQUIVALENCY_HOURS: dict[TaskActionType, float] = {
    TaskActionType.WEB_RESEARCH: 0.10,       # 1 次多源网络检索 ≈ 6 分钟人工精读
    TaskActionType.DOC_EXTRACTION: 0.25,     # 1 份复杂文档提取 ≈ 15 分钟人工梳理
    TaskActionType.CODE_EXECUTION: 0.3333,   # 1 轮代码沙箱调试 ≈ 20 分钟人工编写排错
    TaskActionType.EMAIL_DRAFTING: 0.1667,   # 1 封专业答复草案 ≈ 10 分钟人工构思撰写
    TaskActionType.GENERAL_COGNITION: 0.025, # 1000 Token 推理规划 ≈ 1.5 分钟人工推演
}

ACTION_LABELS: dict[TaskActionType, str] = {
    TaskActionType.WEB_RESEARCH: "多信源深度搜索与交叉比对",
    TaskActionType.DOC_EXTRACTION: "跨格式文档批量提取与整理",
    TaskActionType.CODE_EXECUTION: "代码生成沙箱运行与自动排障",
    TaskActionType.EMAIL_DRAFTING: "邮件意图解析与专业答复拟撰",
    TaskActionType.GENERAL_COGNITION: "长程逻辑推理与复杂决策推演",
}


class LaborAccelerationCalculator:
    """白领劳务效能加速度量化与生产力 ROI 计算器（对标 Hermes Agent Labor Acceleration 理念）。"""

    def __init__(
        self,
        equivalency_matrix: dict[TaskActionType, float] | None = None,
        default_hourly_rate_usd: float = 35.0,
    ) -> None:
        self.matrix = dict(equivalency_matrix or DEFAULT_EQUIVALENCY_HOURS)
        self.default_hourly_rate_usd = default_hourly_rate_usd

    def calculate_task_summary(
        self,
        task_id: str,
        task_elapsed_seconds: float,
        action_counts: dict[TaskActionType, int],
        compute_cost_usd: float = 0.05,
        hourly_rate_usd: float | None = None,
    ) -> LaborAccelerationSummary:
        """根据单任务执行时长与多维行为频次，精确计算挽回工时、效能加速倍率与生产力 ROI。"""
        rate = hourly_rate_usd if hourly_rate_usd is not None else self.default_hourly_rate_usd
        breakdown: list[LaborEquivalencyItem] = []
        total_hours_saved = 0.0

        for action_type, count in action_counts.items():
            if count <= 0:
                continue
            hours_per_unit = self.matrix.get(action_type, 0.05)
            hours_saved = count * hours_per_unit
            total_hours_saved += hours_saved

            breakdown.append(
                LaborEquivalencyItem(
                    action_type=action_type,
                    label=ACTION_LABELS.get(action_type, action_type.value),
                    count=count,
                    hours_per_unit=hours_per_unit,
                    total_hours_saved=hours_saved,
                )
            )

        # 加速倍率: (等效人工秒数 / 实际任务运行秒数)
        equivalent_human_seconds = total_hours_saved * 3600.0
        effective_elapsed = max(1.0, task_elapsed_seconds)
        acceleration_factor = equivalent_human_seconds / effective_elapsed

        # 节省工时估算商业价值 (USD)
        saved_value_usd = total_hours_saved * rate

        # 生产力投入产出比 (ROI Ratio)
        effective_cost = max(0.0001, compute_cost_usd)
        roi_ratio = saved_value_usd / effective_cost

        return LaborAccelerationSummary(
            task_id=task_id,
            task_elapsed_seconds=task_elapsed_seconds,
            total_hours_saved=total_hours_saved,
            acceleration_factor=acceleration_factor,
            hourly_rate_usd=rate,
            estimated_saved_value_usd=saved_value_usd,
            compute_cost_usd=compute_cost_usd,
            roi_ratio=roi_ratio,
            breakdown=breakdown,
        )
