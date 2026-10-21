"""
[INPUT]
- Python 标准库 dataclasses, enum, typing

[OUTPUT]
- TaskActionType: 白领劳务任务行为类型枚举
- LaborEquivalencyItem: 单类行为人工工时等效换算明细
- LaborAccelerationSummary: 白领劳务效能加速与生产力 ROI 全景评估汇总

[POS]
myrm-agent-harness/src/myrm_agent_harness/observability/labor_acceleration/models.py — 劳务效能加速度量化与工时挽回数据契约。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class TaskActionType(str, Enum):
    """白领高频认知与操作行为分类。"""

    WEB_RESEARCH = "web_research"          # 深度网络搜索与多信源交叉比对
    DOC_EXTRACTION = "doc_extraction"      # 跨文档抽取与结构化整理
    CODE_EXECUTION = "code_execution"      # 代码生成、沙箱运行与自动排障
    EMAIL_DRAFTING = "email_drafting"      # 往来邮件意图解析与答复草案拟撰
    GENERAL_COGNITION = "general_cognition"  # 复杂长程推理与规划思考


@dataclass
class LaborEquivalencyItem:
    """单类任务行为的人工工时等效置换明细。"""

    action_type: TaskActionType
    label: string
    count: int
    hours_per_unit: float
    total_hours_saved: float

    def to_dict(self) -> dict[str, object]:
        """序列化为字典。"""
        return {
            "action_type": self.action_type.value,
            "label": self.label,
            "count": self.count,
            "hours_per_unit": round(self.hours_per_unit, 4),
            "total_hours_saved": round(self.total_hours_saved, 4),
        }


@dataclass
class LaborAccelerationSummary:
    """单任务或周期性劳务效能加速与工时挽回综合评估。"""

    task_id: str
    task_elapsed_seconds: float
    total_hours_saved: float
    acceleration_factor: float
    hourly_rate_usd: float = 35.0
    estimated_saved_value_usd: float = 0.0
    compute_cost_usd: float = 0.0
    roi_ratio: float = 0.0
    breakdown: list[LaborEquivalencyItem] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        """序列化为 JSON 字典。"""
        return {
            "task_id": self.task_id,
            "task_elapsed_seconds": round(self.task_elapsed_seconds, 2),
            "total_hours_saved": round(self.total_hours_saved, 3),
            "acceleration_factor": round(self.acceleration_factor, 1),
            "hourly_rate_usd": round(self.hourly_rate_usd, 2),
            "estimated_saved_value_usd": round(self.estimated_saved_value_usd, 2),
            "compute_cost_usd": round(self.compute_cost_usd, 4),
            "roi_ratio": round(self.roi_ratio, 1),
            "breakdown": [item.to_dict() for item in self.breakdown],
            "created_at": self.created_at,
        }
