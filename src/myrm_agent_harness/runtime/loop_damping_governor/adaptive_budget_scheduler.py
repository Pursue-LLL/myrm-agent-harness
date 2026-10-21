"""自适应循环计算预算调度器模块.

对标 LoopCoder-v2 论文“Only Loop Once / 循环深度与效果非单调”核心发现：
根据用户输入信息熵与涉及代码规模，自适应分配阶梯计算预算（3/8/20轮），
终结一刀切固定 50 步硬编码导致的无序空转与算力浪费。

[INPUT]
- __future__
- logging

[OUTPUT]
- logger
- TIER_BUDGET_MAP
- AdaptiveBudgetScheduler

[POS]
自适应循环计算预算调度器模块.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.runtime.loop_damping_governor.oscillation_guard_types import (
    ComputeBudgetDecision,
    TaskComplexityTier,
)

logger = logging.getLogger(__name__)

# 阶梯预算映射表
TIER_BUDGET_MAP: dict[TaskComplexityTier, int] = {
    TaskComplexityTier.POINT_TASK: 3,
    TaskComplexityTier.STANDARD_FEATURE: 8,
    TaskComplexityTier.DEEP_REFACTOR: 20,
}


class AdaptiveBudgetScheduler:
    """自适应循环计算预算调度器."""

    def __init__(
        self,
        initial_tier: TaskComplexityTier = TaskComplexityTier.STANDARD_FEATURE,
    ) -> None:
        self._current_tier: TaskComplexityTier = initial_tier
        self._max_loops: int = TIER_BUDGET_MAP[initial_tier]
        self._escalation_history: list[str] = []

    @property
    def current_tier(self) -> TaskComplexityTier:
        """获取当前任务复杂度分级."""
        return self._current_tier

    @property
    def max_loops(self) -> int:
        """获取当前生效的循环预算上限."""
        return self._max_loops

    @classmethod
    def infer_tier_from_input(
        cls,
        user_prompt: str,
        context_files_count: int = 1,
        estimated_code_lines: int = 0,
    ) -> TaskComplexityTier:
        """基于用户 Prompt 与上下文特征智能推断初始任务复杂度."""
        prompt_lower = user_prompt.lower()

        # 深度架构演进特征
        deep_keywords = ("refactor", "architecture", "redesign", "重构", "架构", "迁移", "演进")
        if (
            context_files_count > 5
            or estimated_code_lines > 500
            or any(k in prompt_lower for k in deep_keywords)
        ):
            return TaskComplexityTier.DEEP_REFACTOR

        # 极简点状任务特征
        simple_keywords = ("typo", "fix typo", "print", "拼写", "微调", "只读", "查询")
        if (
            context_files_count <= 1
            and estimated_code_lines < 50
            and len(user_prompt) < 120
            and any(k in prompt_lower for k in simple_keywords)
        ):
            return TaskComplexityTier.POINT_TASK

        # 默认标准功能开发
        return TaskComplexityTier.STANDARD_FEATURE

    def escalate_tier(self, new_tier: TaskComplexityTier, reason: str) -> bool:
        """单向动态升格计算预算（严禁降级已分配的预算保证单调安全）."""
        current_rank = list(TaskComplexityTier).index(self._current_tier)
        new_rank = list(TaskComplexityTier).index(new_tier)

        if new_rank > current_rank:
            old_tier = self._current_tier
            self._current_tier = new_tier
            self._max_loops = TIER_BUDGET_MAP[new_tier]
            msg = f"Escalated compute budget: {old_tier} -> {new_tier} (max loops: {self._max_loops}). Reason: {reason}"
            self._escalation_history.append(msg)
            logger.info(msg)
            return True

        logger.debug(
            "Rejected tier downgrade or no-op from %s to %s. Keeping current budget.",
            self._current_tier,
            new_tier,
        )
        return False

    def evaluate_budget(self, current_loop: int) -> ComputeBudgetDecision:
        """评估当前迭代步数的预算消耗情况."""
        is_exhausted = current_loop >= self._max_loops
        remaining = max(0, self._max_loops - current_loop)

        return ComputeBudgetDecision(
            tier=self._current_tier,
            allocated_max_loops=self._max_loops,
            current_loop=current_loop,
            is_exhausted=is_exhausted,
            remaining_loops=remaining,
        )
