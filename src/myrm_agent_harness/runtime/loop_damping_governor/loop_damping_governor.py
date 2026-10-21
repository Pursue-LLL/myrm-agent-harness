"""自适应循环计算预算调度与思考振荡阻尼治理中枢模块.

本模块协同预算调度器与振荡探针，在每轮迭代边界执行阻尼判决，
实现饱和早停、振荡熔断并生成人机裁决卡，彻底守住智能体推理质量与 Token 算力安全。

[INPUT]
- __future__
- logging

[OUTPUT]
- logger
- LoopDampingGovernor

[POS]
自适应循环计算预算调度与思考振荡阻尼治理中枢模块.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.runtime.loop_damping_governor.adaptive_budget_scheduler import (
    AdaptiveBudgetScheduler,
)
from myrm_agent_harness.runtime.loop_damping_governor.oscillation_guard_types import (
    LoopDampingAction,
    LoopDampingVerdict,
    TaskComplexityTier,
)
from myrm_agent_harness.runtime.loop_damping_governor.thought_oscillation_detector import (
    ThoughtOscillationDetector,
)

logger = logging.getLogger(__name__)


class LoopDampingGovernor:
    """循环计算预算与思考振荡综合治理中枢."""

    def __init__(
        self,
        initial_tier: TaskComplexityTier = TaskComplexityTier.STANDARD_FEATURE,
        scheduler: AdaptiveBudgetScheduler | None = None,
        detector: ThoughtOscillationDetector | None = None,
    ) -> None:
        self.scheduler: AdaptiveBudgetScheduler = scheduler or AdaptiveBudgetScheduler(
            initial_tier=initial_tier
        )
        self.detector: ThoughtOscillationDetector = detector or ThoughtOscillationDetector()

    def escalate_budget(self, new_tier: TaskComplexityTier, reason: str) -> bool:
        """根据最新发现的依赖复杂度，单向升格任务计算预算."""
        return self.scheduler.escalate_tier(new_tier, reason)

    def evaluate_step(
        self,
        step_index: int,
        target_identifier: str,
        state_signature: str,
        summary: str = "",
        is_model_saturated: bool = False,
    ) -> LoopDampingVerdict:
        """在每轮工具执行或思考后执行综合阻尼评估.

        判决优先级：
        1. 思考振荡探针判定（乒乓编辑 / 死循环工具链） -> DAMPED_HALT_OSCILLATION（立即阻尼熔断）
        2. 模型意图饱和判定 -> EARLY_FINISH_SATURATED（自适应收敛早停）
        3. 自适应计算预算耗尽 -> BUDGET_EXHAUSTED（强制收敛退出）
        4. 正常安全迭代 -> CONTINUE（继续执行）
        """
        # 1. 记录本轮动作指纹
        self.detector.record_action(
            step_index=step_index,
            target_identifier=target_identifier,
            state_signature=state_signature,
            summary=summary,
        )

        # 2. 检查思考振荡
        oscillation = self.detector.detect_oscillation()
        budget_decision = self.scheduler.evaluate_budget(step_index)

        if oscillation.is_oscillating:
            logger.warning(
                "LoopDampingGovernor: triggering DAMPED_HALT_OSCILLATION at step %d: %s",
                step_index,
                oscillation.explanation,
            )
            return LoopDampingVerdict(
                action=LoopDampingAction.DAMPED_HALT_OSCILLATION,
                current_step=step_index,
                budget=budget_decision,
                oscillation=oscillation,
                message=oscillation.explanation or "Thought oscillation detected",
            )

        # 3. 检查意图与信息增量饱和
        if is_model_saturated:
            msg = f"Loop saturated at step {step_index}: output delta marginal"
            logger.info("LoopDampingGovernor: triggering EARLY_FINISH_SATURATED: %s", msg)
            return LoopDampingVerdict(
                action=LoopDampingAction.EARLY_FINISH_SATURATED,
                current_step=step_index,
                budget=budget_decision,
                oscillation=oscillation,
                message=msg,
            )

        # 4. 检查自适应计算预算耗尽
        if budget_decision.is_exhausted:
            msg = (
                f"Loop compute budget exhausted at step {step_index}: "
                f"reached limit of {budget_decision.allocated_max_loops} loops for tier '{budget_decision.tier}'"
            )
            logger.warning("LoopDampingGovernor: triggering BUDGET_EXHAUSTED: %s", msg)
            return LoopDampingVerdict(
                action=LoopDampingAction.BUDGET_EXHAUSTED,
                current_step=step_index,
                budget=budget_decision,
                oscillation=oscillation,
                message=msg,
            )

        # 5. 允许健康迭代继续
        return LoopDampingVerdict(
            action=LoopDampingAction.CONTINUE,
            current_step=step_index,
            budget=budget_decision,
            oscillation=oscillation,
            message="Healthy iteration loop",
        )
