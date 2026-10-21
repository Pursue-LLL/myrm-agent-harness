"""自适应循环计算预算调度器、思考振荡漂移探针与阻尼早停决策套件.

对外导出核心类型、预算调度器、振荡探针与阻尼治理中枢.

[INPUT]
- (none — 标准库与内建依赖)

[OUTPUT]
- (模块级副作用与注册)

[POS]
自适应循环计算预算调度器、思考振荡漂移探针与阻尼早停决策套件.
"""

from myrm_agent_harness.runtime.loop_damping_governor.adaptive_budget_scheduler import (
    AdaptiveBudgetScheduler,
)
from myrm_agent_harness.runtime.loop_damping_governor.loop_damping_governor import (
    LoopDampingGovernor,
)
from myrm_agent_harness.runtime.loop_damping_governor.oscillation_guard_types import (
    ActionFingerprint,
    ComputeBudgetDecision,
    HumanTiebreakerCard,
    LoopDampingAction,
    LoopDampingVerdict,
    OscillationPatternType,
    OscillationVerdict,
    TaskComplexityTier,
)
from myrm_agent_harness.runtime.loop_damping_governor.thought_oscillation_detector import (
    ThoughtOscillationDetector,
)

__all__ = [
    "ActionFingerprint",
    "AdaptiveBudgetScheduler",
    "ComputeBudgetDecision",
    "HumanTiebreakerCard",
    "LoopDampingAction",
    "LoopDampingGovernor",
    "LoopDampingVerdict",
    "OscillationPatternType",
    "OscillationVerdict",
    "TaskComplexityTier",
    "ThoughtOscillationDetector",
]
