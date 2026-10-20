"""
[INPUT]
- time (time)
- typing (Literal)
- pydantic (BaseModel, Field)

[OUTPUT]
- AdvisorInterventionLevel: 旁路军师三级干预层级字面量 (aside | concern | blocker)
- AdvisorReviewTrigger: 旁路审查触发策略字面量
- AdvisorIntervention: 结构化单项干预建议条目实体
- AdvisorChannelConfig: 旁路通道运行配置实体
- AdvisorReviewResult: 单次审查全量判定结果实体

[POS]
Harness 框架层双模型实时旁路军师评审通道数据契约（Topic 12 · 第 17 项）。
对齐 oh-my-pi 架构，严格定义 aside（静默旁白）、concern（担忧预警）与 blocker（硬性阻断）三级强协议，0 Any。
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

AdvisorInterventionLevel = Literal["aside", "concern", "blocker"]
AdvisorReviewTrigger = Literal["all_tool_calls", "risk_pattern", "periodic_turn"]


class AdvisorIntervention(BaseModel):
    """单项旁路军师注入干预建议实体。"""

    intervention_id: str = Field(..., description="干预建议唯一标识 ID")
    level: AdvisorInterventionLevel = Field(
        ...,
        description="干预层级：aside (旁白提示) | concern (担忧预警) | blocker (硬性阻断)",
    )
    title: str = Field(..., min_length=1, description="干预摘要标题")
    message: str = Field(..., min_length=1, description="详尽的审查理由与风险剖析")
    suggested_action: str | None = Field(default=None, description="建议主模型采取的纠偏动作")
    created_at: float = Field(default_factory=time.time, description="生成时间戳")
    duration_ms: float = Field(default=0.0, ge=0.0, description="Advisor 审校耗时 (毫秒)")
    tokens_used: int = Field(default=0, ge=0, description="Advisor 独立消耗的 Token 数")


class AdvisorChannelConfig(BaseModel):
    """Advisor 旁路审校通道运行配置。"""

    enabled: bool = Field(default=True, description="是否启用双模型实时旁路审查")
    trigger_mode: AdvisorReviewTrigger = Field(
        default="all_tool_calls",
        description="审查触发模式：all_tool_calls | risk_pattern | periodic_turn",
    )
    block_dangerous_patterns: bool = Field(
        default=True,
        description="是否对高危破坏性操作强制产生 blocker 硬阻断",
    )
    max_review_timeout_ms: float = Field(
        default=3000.0,
        ge=500.0,
        description="旁路审校单次最大超时时间 (毫秒)",
    )


class AdvisorReviewResult(BaseModel):
    """单步动作的 Advisor 综合审查判定结果。"""

    is_blocked: bool = Field(..., description="是否触发 blocker 硬阻断（熔断主 Agent 执行）")
    highest_level: AdvisorInterventionLevel | None = Field(
        default=None,
        description="本次检出的最高干预等级",
    )
    interventions: list[AdvisorIntervention] = Field(
        default_factory=list,
        description="生成的结构化干预建议列表",
    )
    summary: str = Field(default="", description="旁路审校决策摘要")
