"""强类型契约定义：极紧凑 Working Memory 投影器、显式 Resource Loader 与超低 Harness Tax 控制器。

对标 Databricks 真实 PR 基准评测 Pareto 前沿 Pi Agent 极简工程心法，将框架税 (Harness Tax) 降至极限。

[INPUT]
- 无外部动态依赖，定义资源装配、工具动态收缩、Working Memory 投影契约。

[OUTPUT]
- ToolExposurePolicy: 工具暴露策略枚举 (MINIMAL_CORE_ONLY / INTENT_ADAPTIVE / FULL_CAPABILITY)
- ToolDescriptor: 工具元数据与 Schema 开销描述
- ResourceLoadBundle: 显式装配的运行时指令与资源包
- CompactWorkingMemoryView: 投影后的极紧凑 Working Memory 视图
- HarnessTaxConfig: Harness Tax 控制器配置
- HarnessTaxAuditReport: 框架税开销审计与节约分析报告

[POS]
- 位于 context_management/harness_tax/harness_tax_types.py
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Sequence
from langchain_core.messages import BaseMessage


class ToolExposurePolicy(StrEnum):
    """工具最小化暴露策略枚举。"""

    MINIMAL_CORE_ONLY = "minimal_core_only"
    INTENT_ADAPTIVE = "intent_adaptive"
    FULL_CAPABILITY = "full_capability"


@dataclass(frozen=True)
class ToolDescriptor:
    """单个工具的元数据及 Schema Token 消耗契约。"""

    name: str
    description: str
    schema_tokens_estimate: int
    is_core: bool = False
    category: str = "general"


@dataclass(frozen=True)
class ResourceLoadBundle:
    """显式编译加载的运行时资源包契约。"""

    profile_id: str
    system_instructions: str
    active_skill_names: list[str]
    prompt_template: str
    loaded_tokens: int


@dataclass(frozen=True)
class CompactWorkingMemoryView:
    """投影后的极紧凑 Working Memory 上下文契约。"""

    session_id: str
    projected_messages: list[BaseMessage]
    original_tokens: int
    projected_tokens: int
    harness_tax_saved_tokens: int
    reduction_ratio: float


@dataclass
class HarnessTaxConfig:
    """超低 Harness Tax 控制器配置。"""

    max_active_tools: int = 4
    core_tool_whitelist: tuple[str, ...] = (
        "read_file",
        "write_file",
        "edit_file",
        "bash_run",
    )
    exposure_policy: ToolExposurePolicy = ToolExposurePolicy.MINIMAL_CORE_ONLY
    enable_active_branch_projection: bool = True
    recent_turns_retention: int = 3


@dataclass(frozen=True)
class HarnessTaxAuditReport:
    """Harness Tax 审计与单轮成本节约报告。"""

    base_tool_schema_tokens: int
    projected_tool_schema_tokens: int
    tool_tokens_saved: int
    context_tokens_saved: int
    total_tokens_saved: int
    estimated_cost_savings_pct: float
