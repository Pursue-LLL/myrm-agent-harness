"""强类型契约定义：百万 Token 超大上下文动态自适应压实与双轨绝对上限守卫套件。

[INPUT]
- 无外部动态依赖，定义领域契约。

[OUTPUT]
- CompactionTrackType: 阈值轨道类型枚举 (物理上限轨 / 操作软上限轨 / 操作硬上限轨)
- CompactionTierAction: 分级动作枚举 (无动作 / Tier 1 工具外部化 / Tier 2 增量摘要 / Tier 3 紧急守卫)
- OffloadedToolArtifact: 被外部化持久化的工具输出元数据
- ContextBudgetForecast: 延迟与成本多维预估模型
- MillionTokenCeilingConfig: 双轨绝对上限守卫配置
- MillionTokenCompactionResult: 阶梯式压实执行结果

[POS]
- 位于 context_management/million_token_ceiling/million_token_ceiling_types.py
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Sequence
from langchain_core.messages import BaseMessage


class CompactionTrackType(StrEnum):
    """上下文阈值轨道类型。"""

    PHYSICAL = "physical"
    OPERATIONAL_SOFT = "operational_soft"
    OPERATIONAL_HARD = "operational_hard"


class CompactionTierAction(StrEnum):
    """阶梯式压实动作枚举。"""

    NONE = "none"
    TIER1_OFFLOAD_TOOLS = "tier1_offload_tools"
    TIER2_ROLLING_SUMMARY = "tier2_rolling_summary"
    TIER3_EMERGENCY_GUARD = "tier3_emergency_guard"


@dataclass(frozen=True)
class OffloadedToolArtifact:
    """被外部化落盘的工具调用输出制品契约。"""

    tool_call_id: str
    tool_name: str
    original_tokens: int
    ref_handle: str
    disk_path: str
    preview_snippet: str
    created_at_epoch: float


@dataclass(frozen=True)
class ContextBudgetForecast:
    """上下文延迟与成本多维预算预估模型。"""

    current_tokens: int
    effective_threshold: int
    physical_limit: int
    operational_soft_ceiling: int
    operational_hard_ceiling: int
    projected_ttft_ms: float
    projected_turn_cost_usd: float
    tokens_saved_by_compaction: int
    cost_saved_usd: float
    compaction_starvation_prevented: bool


@dataclass
class MillionTokenCeilingConfig:
    """双轨动态压实与延迟成本绝对上限守卫配置。"""

    physical_context_limit: int = 1_050_000
    ratio_threshold: float = 0.75
    operational_soft_ceiling: int = 64_000
    operational_hard_ceiling: int = 96_000
    min_tool_offload_tokens: int = 300
    protected_recent_turns: int = 3
    cost_per_1k_input_tokens_usd: float = 0.003
    base_ttft_ms: float = 350.0
    ttft_ms_per_10k_tokens: float = 450.0
    context_storage_subpath: str = ".context/tools"

    @property
    def naive_ratio_threshold(self) -> int:
        """纯按比例计算得到的传统阈值（在 1M 模型下会引发 Starvation 饥饿）。"""
        return int(self.physical_context_limit * self.ratio_threshold)

    @property
    def effective_compress_threshold(self) -> int:
        """动态自适应软上限（解决大模型下的饥饿问题）。"""
        return min(self.naive_ratio_threshold, self.operational_soft_ceiling)

    @property
    def effective_hard_ceiling(self) -> int:
        """动态自适应硬上限。"""
        return min(
            int(self.physical_context_limit * 0.95),
            self.operational_hard_ceiling,
        )


@dataclass
class MillionTokenCompactionResult:
    """阶梯式压实执行结果。"""

    tier_action: CompactionTierAction
    before_tokens: int
    after_tokens: int
    offloaded_artifacts: list[OffloadedToolArtifact] = field(default_factory=list)
    messages: list[BaseMessage] = field(default_factory=list)
    forecast: ContextBudgetForecast | None = None
    is_compacted: bool = False
