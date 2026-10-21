"""自适应计算预算与思考振荡阻尼套件类型定义模块.

本模块定义任务复杂度分级、振荡模式、阻尼判决动作与人机决策卡的核心数据模型。
严禁使用 Any 类型，确保完全强类型化。

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- TaskComplexityTier
- OscillationPatternType
- LoopDampingAction
- ActionFingerprint
- HumanTiebreakerCard
- OscillationVerdict
- ComputeBudgetDecision
- LoopDampingVerdict

[POS]
自适应计算预算与思考振荡阻尼套件类型定义模块.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class TaskComplexityTier(StrEnum):
    """任务复杂度阶梯枚举，决定自适应迭代预算上限."""

    POINT_TASK = "point_task"  # 极简点状任务（单文件微调/只读查询），建议预算上限 3 轮
    STANDARD_FEATURE = "standard_feature"  # 标准功能开发/Bug修复/单测，建议预算上限 8 轮
    DEEP_REFACTOR = "deep_refactor"  # 深度架构演进/多模块重构，建议预算上限 20 轮


class OscillationPatternType(StrEnum):
    """思考与行为振荡模式枚举."""

    PING_PONG_EDIT = "ping_pong_edit"  # 对同一目标在两个对立状态之间来回横跳修改（A -> B -> A）
    ZERO_SEMANTIC_PROGRESS = "zero_semantic_progress"  # 连续多轮无实质进展，收益饱和
    CYCLIC_TOOL_CHAIN = "cyclic_tool_chain"  # 工具调用序列呈现确定性闭环死循环


class LoopDampingAction(StrEnum):
    """阻尼判决指令动作枚举."""

    CONTINUE = "continue"  # 处于健康迭代区间，继续执行
    EARLY_FINISH_SATURATED = "early_finish_saturated"  # 边际收益归零饱和，平稳早停
    DAMPED_HALT_OSCILLATION = "damped_halt_oscillation"  # 探测到思考振荡，执行强制阻尼熔断
    BUDGET_EXHAUSTED = "budget_exhausted"  # 达到自适应动态计算预算上限，强制收敛退出


@dataclass(frozen=True)
class ActionFingerprint:
    """单个执行动作或文件修改的轻量级特征指纹."""

    step_index: int
    target_identifier: str  # 目标标识符（如文件路径或工具名）
    state_signature: str  # 内容状态签名或参数摘要哈希
    summary: str = ""
    timestamp_ms: float = field(default_factory=lambda: time.time() * 1000)


@dataclass(frozen=True)
class HumanTiebreakerCard:
    """当思考振荡被阻断时生成的人机决策卡."""

    dispute_summary: str
    affected_target: str
    option_a_summary: str
    option_b_summary: str
    recommended_option: str
    created_at_ms: float = field(default_factory=lambda: time.time() * 1000)


@dataclass(frozen=True)
class OscillationVerdict:
    """思考振荡探针的检测判决对象."""

    is_oscillating: bool
    pattern: OscillationPatternType | None = None
    affected_targets: list[str] = field(default_factory=list)
    explanation: str | None = None
    tiebreaker_card: HumanTiebreakerCard | None = None


@dataclass(frozen=True)
class ComputeBudgetDecision:
    """动态计算预算判决结果."""

    tier: TaskComplexityTier
    allocated_max_loops: int
    current_loop: int
    is_exhausted: bool
    remaining_loops: int


@dataclass(frozen=True)
class LoopDampingVerdict:
    """综合阻尼决策结果对象."""

    action: LoopDampingAction
    current_step: int
    budget: ComputeBudgetDecision
    oscillation: OscillationVerdict | None = None
    message: str = ""
