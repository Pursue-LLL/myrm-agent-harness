"""Skill Quality Calculator

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- .types::SkillQualityScore (POS: 质量评分数据结构)

[OUTPUT]
- SkillExecutionSample: 单次skill执行样本数据结构
- SkillQualityCalculator: 质量评分计算器（无状态，纯函数）

[POS]
Quality score calculator. Computes 5-dimension quality scores from raw execution samples.

"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .protocols import SkillMetricsProvider
    from .types import SkillQualityScore

logger = logging.getLogger(__name__)


@dataclass
class SkillExecutionSample:
    """单次skill执行样本

    Attributes:
        skill_id: Skill标识符
        success: 执行是否成功
        tokens_used: 使用的token数量
        execution_time: 执行时间（秒）
        user_feedback: 用户反馈 (-1=差, 0=中, 1=好)
        timestamp: 执行时间戳
    """

    skill_id: str
    success: bool
    tokens_used: int
    execution_time: float
    user_feedback: int | None = None
    timestamp: datetime = None


class SkillQualityCalculator:
    """Skill质量评分计算器

    从原始样本数据计算5维质量评分的核心算法。
    设计为无状态纯函数，确保框架层独立可用，无业务耦合。

    5维评分：
    1. success_rate: 成功率 (0-1)
    2. token_efficiency: Token效率 (0-1)
    3. execution_time: 执行时间效率 (0-1)
    4. user_satisfaction: 用户满意度 (0-1)
    5. call_frequency: 调用频率 (0-1，由外部提供）
    """

    def __init__(
        self,
        token_baseline: int = 1000,
        time_baseline: float = 10.0,
        metrics_provider: SkillMetricsProvider | None = None,
    ):
        """初始化质量计算器

        Args:
            token_baseline: Token效率基准（默认1000 tokens）
            time_baseline: 执行时间基准（默认10秒）
            metrics_provider: 可选的Skill metrics提供者（用于funnel分析）
        """
        self.token_baseline = token_baseline
        self.time_baseline = time_baseline
        self.metrics_provider = metrics_provider

    async def calculate(
        self, samples: list[SkillExecutionSample], call_frequency: float = 0.5, skill_id: str | None = None
    ) -> SkillQualityScore:
        """从样本数据计算质量评分

        Args:
            samples: skill执行样本列表
            call_frequency: 调用频率（0-1，由外部统计系统提供）
            skill_id: Skill ID（用于查询funnel metrics）

        Returns:
            SkillQualityScore: 5维质量评分 + 可选funnel metrics
        """
        from .types import SkillQualityScore

        if not samples:
            # 无样本时返回默认评分（中等水平）
            score = SkillQualityScore(
                success_rate=0.5,
                token_efficiency=0.5,
                execution_time=0.5,
                user_satisfaction=0.5,
                call_frequency=call_frequency,
            )
            # Attach funnel metrics if provider available
            if self.metrics_provider and skill_id:
                try:
                    score.funnel_metrics = await self.metrics_provider.get_skill_metrics(skill_id)
                except Exception as e:
                    logger.warning(f"Failed to fetch funnel metrics for {skill_id}: {e}")
            return score

        # 1. 计算成功率
        success_rate = self._calculate_success_rate(samples)

        # 2. 计算token效率
        token_efficiency = self._calculate_token_efficiency(samples)

        # 3. 计算执行时间效率
        execution_time = self._calculate_execution_time_efficiency(samples)

        # 4. 计算用户满意度
        user_satisfaction = self._calculate_user_satisfaction(samples)

        logger.debug(
            f"Quality calculated for {samples[0].skill_id}: "
            f"success={success_rate:.2f}, token={token_efficiency:.2f}, "
            f"time={execution_time:.2f}, satisfaction={user_satisfaction:.2f}"
        )

        score = SkillQualityScore(
            success_rate=success_rate,
            token_efficiency=token_efficiency,
            execution_time=execution_time,
            user_satisfaction=user_satisfaction,
            call_frequency=call_frequency,
        )

        # Attach funnel metrics if provider available
        if self.metrics_provider and skill_id:
            try:
                score.funnel_metrics = await self.metrics_provider.get_skill_metrics(skill_id)
                if score.funnel_metrics:
                    logger.debug(
                        f"Funnel metrics attached for {skill_id}: "
                        f"selections={score.funnel_metrics.total_selections}, "
                        f"applied={score.funnel_metrics.applied_count}, "
                        f"fallback_rate={score.funnel_metrics.fallback_rate:.1%}"
                    )
            except Exception as e:
                logger.warning(f"Failed to fetch funnel metrics for {skill_id}: {e}")

        return score

    def _calculate_success_rate(self, samples: list[SkillExecutionSample]) -> float:
        """计算成功率

        成功率 = 成功次数 / 总次数

        Args:
            samples: 样本列表

        Returns:
            float: 成功率 (0-1)
        """
        success_count = sum(1 for s in samples if s.success)
        return success_count / len(samples)

    def _calculate_token_efficiency(self, samples: list[SkillExecutionSample]) -> float:
        """计算token效率

        Token效率 = baseline / (avg_tokens + 1)
        - 使用token越少，效率越高
        - 归一化到0-1范围（超过baseline的效率<0.5）

        Args:
            samples: 样本列表

        Returns:
            float: Token效率 (0-1)
        """
        avg_tokens = sum(s.tokens_used for s in samples) / len(samples)

        # 归一化：baseline为参考点
        efficiency = self.token_baseline / (avg_tokens + 1)

        # 限制在0-1范围
        return max(0.0, min(1.0, efficiency))

    def _calculate_execution_time_efficiency(self, samples: list[SkillExecutionSample]) -> float:
        """计算执行时间效率

        时间效率 = baseline / (avg_time + 0.1)
        - 执行时间越短，效率越高
        - 归一化到0-1范围（超过baseline的效率<0.5）

        Args:
            samples: 样本列表

        Returns:
            float: 时间效率 (0-1)
        """
        avg_time = sum(s.execution_time for s in samples) / len(samples)

        # 归一化：baseline为参考点
        efficiency = self.time_baseline / (avg_time + 0.1)

        # 限制在0-1范围
        return max(0.0, min(1.0, efficiency))

    def _calculate_user_satisfaction(self, samples: list[SkillExecutionSample]) -> float:
        """计算用户满意度

        满意度 = (avg_feedback + 1) / 2
        - 反馈范围：-1（差）, 0（中）, 1（好）
        - 映射到0-1范围
        - 无反馈默认0.5

        Args:
            samples: 样本列表

        Returns:
            float: 用户满意度 (0-1)
        """
        feedbacks = [s.user_feedback for s in samples if s.user_feedback is not None]

        if not feedbacks:
            # 无反馈时默认中等
            return 0.5

        avg_feedback = sum(feedbacks) / len(feedbacks)

        # 映射-1到1 → 0到1
        satisfaction = (avg_feedback + 1) / 2

        return max(0.0, min(1.0, satisfaction))
