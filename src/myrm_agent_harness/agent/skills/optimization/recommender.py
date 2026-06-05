"""Skill Optimization Recommendation Engine

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- .protocols.SkillExecutionProvider (POS: 执行事件提供者)
- .protocols.SkillOptimizationStorage (POS: 存储层接口)
- .quality_calculator.QualityCalculator (POS: 质量计算器)
- datetime (POS: 时间处理)

[OUTPUT]
- OptimizationRecommendation: 优化推荐数据类
- RecommendationEngine: 推荐引擎类

[POS]
Skill optimization recommendation engine (framework layer). Intelligently identifies skills worth optimizing.

"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .protocols import SkillExecutionProvider, SkillOptimizationStorage
    from .quality_calculator import QualityCalculator
    from .types import SkillQualityScore


class RecommendationReason(StrEnum):
    """推荐原因"""

    LOW_QUALITY_HIGH_FREQ = "low_quality_high_frequency"  # 低质量高频率
    LONG_NOT_OPTIMIZED = "long_not_optimized"  # 长期未优化
    NEGATIVE_USER_FEEDBACK = "negative_user_feedback"  # 用户反馈差
    HIGH_FAILURE_RATE = "high_failure_rate"  # 高失败率
    PERFORMANCE_DEGRADATION = "performance_degradation"  # 性能下降


@dataclass
class OptimizationRecommendation:
    """优化推荐

    Attributes:
        skill_id: Skill ID
        priority_score: 优先级评分（0.0-1.0，越高越优先）
        quality_score: 当前质量评分
        reasons: 推荐原因列表
        details: 详细信息（含各维度分数）
        last_optimized_at: 上次优化时间（None表示从未优化）
        execution_count_7d: 最近7天执行次数
    """

    skill_id: str
    priority_score: float
    quality_score: SkillQualityScore
    reasons: list[RecommendationReason]
    details: dict[str, float]
    last_optimized_at: datetime | None
    execution_count_7d: int


class RecommendationEngine:
    """Skill优化推荐引擎

    智能识别值得优化的skill，基于多维度评分。

    Args:
        execution_provider: 执行数据提供者
        storage: 存储层
        quality_calculator: 质量计算器
        quality_threshold: 质量阈值（默认0.7，低于此值优先推荐）
        high_freq_threshold: 高频阈值（默认10次/7天）
        long_not_optimized_days: 长期未优化天数（默认30天）
    """

    def __init__(
        self,
        execution_provider: SkillExecutionProvider,
        storage: SkillOptimizationStorage,
        quality_calculator: QualityCalculator,
        quality_threshold: float = 0.7,
        high_freq_threshold: int = 10,
        long_not_optimized_days: int = 30,
    ):
        self.execution_provider = execution_provider
        self.storage = storage
        self.quality_calculator = quality_calculator
        self.quality_threshold = quality_threshold
        self.high_freq_threshold = high_freq_threshold
        self.long_not_optimized_days = long_not_optimized_days

    async def get_recommendations(
        self, limit: int = 10, min_priority_score: float = 0.5
    ) -> list[OptimizationRecommendation]:
        """获取优化推荐列表

        Args:
            limit: 返回数量
            min_priority_score: 最低优先级评分（过滤低优先级推荐）

        Returns:
            优化推荐列表，按priority_score降序
        """
        skill_ids = await self.execution_provider.get_all_skill_ids()
        recommendations: list[OptimizationRecommendation] = []

        for skill_id in skill_ids:
            recommendation = await self._evaluate_skill(skill_id)

            if recommendation and recommendation.priority_score >= min_priority_score:
                recommendations.append(recommendation)

        recommendations.sort(key=lambda x: x.priority_score, reverse=True)
        return recommendations[:limit]

    async def _evaluate_skill(self, skill_id: str) -> OptimizationRecommendation | None:
        """评估单个skill

        Args:
            skill_id: Skill ID

        Returns:
            优化推荐对象，不符合推荐条件返回None
        """
        samples = await self.execution_provider.get_skill_executions(skill_id=skill_id, days=7)

        if not samples:
            return None

        quality_score = self.quality_calculator.calculate_quality_score(samples)
        execution_count = len(samples)

        last_optimization = await self.storage.get_optimization_record(skill_id)
        last_optimized_at = last_optimization.started_at if last_optimization else None

        quality_factor = self._calculate_quality_factor(quality_score.overall_score)
        frequency_factor = self._calculate_frequency_factor(execution_count)
        freshness_factor = self._calculate_freshness_factor(last_optimized_at)
        feedback_factor = self._calculate_feedback_factor(samples)
        failure_factor = self._calculate_failure_factor(samples)

        priority_score = (
            quality_factor * 0.35
            + frequency_factor * 0.25
            + freshness_factor * 0.20
            + feedback_factor * 0.10
            + failure_factor * 0.10
        )

        reasons = self._determine_reasons(
            quality_score=quality_score.overall_score,
            execution_count=execution_count,
            last_optimized_at=last_optimized_at,
            samples=samples,
        )

        if not reasons:
            return None

        return OptimizationRecommendation(
            skill_id=skill_id,
            priority_score=priority_score,
            quality_score=quality_score,
            reasons=reasons,
            details={
                "quality_factor": quality_factor,
                "frequency_factor": frequency_factor,
                "freshness_factor": freshness_factor,
                "feedback_factor": feedback_factor,
                "failure_factor": failure_factor,
            },
            last_optimized_at=last_optimized_at,
            execution_count_7d=execution_count,
        )

    def _calculate_quality_factor(self, quality_score: float) -> float:
        """计算质量因子（0.0-1.0）"""
        if quality_score < self.quality_threshold:
            return 1.0 - quality_score
        return 0.0

    def _calculate_frequency_factor(self, execution_count: int) -> float:
        """计算频率因子（0.0-1.0）"""
        if execution_count >= self.high_freq_threshold:
            return min(execution_count / (self.high_freq_threshold * 2), 1.0)
        return execution_count / self.high_freq_threshold

    def _calculate_freshness_factor(self, last_optimized_at: datetime | None) -> float:
        """计算新鲜度因子（0.0-1.0）"""
        if last_optimized_at is None:
            return 1.0

        days_since_optimization = (datetime.now() - last_optimized_at).days

        if days_since_optimization >= self.long_not_optimized_days:
            return min(days_since_optimization / (self.long_not_optimized_days * 2), 1.0)

        return days_since_optimization / self.long_not_optimized_days

    def _calculate_feedback_factor(self, samples: list) -> float:
        """计算用户反馈因子（0.0-1.0）

        Args:
            samples: SkillExecutionSample列表
        """
        feedback_samples = [s for s in samples if s.user_feedback is not None]

        if not feedback_samples:
            return 0.0

        avg_feedback = sum(s.user_feedback for s in feedback_samples) / len(feedback_samples)

        if avg_feedback < 0:
            return abs(avg_feedback)

        return 0.0

    def _calculate_failure_factor(self, samples: list) -> float:
        """计算失败率因子（0.0-1.0）

        Args:
            samples: SkillExecutionSample列表
        """
        failure_count = sum(1 for s in samples if not s.success)
        failure_rate = failure_count / len(samples) if samples else 0.0

        if failure_rate > 0.2:
            return min(failure_rate * 2, 1.0)

        return 0.0

    def _determine_reasons(
        self, quality_score: float, execution_count: int, last_optimized_at: datetime | None, samples: list
    ) -> list[RecommendationReason]:
        """确定推荐原因

        Args:
            quality_score: 质量评分
            execution_count: 执行次数
            last_optimized_at: 上次优化时间
            samples: SkillExecutionSample列表
        """
        reasons: list[RecommendationReason] = []

        if quality_score < self.quality_threshold and execution_count >= self.high_freq_threshold:
            reasons.append(RecommendationReason.LOW_QUALITY_HIGH_FREQ)

        if last_optimized_at is None or (datetime.now() - last_optimized_at).days >= self.long_not_optimized_days:
            reasons.append(RecommendationReason.LONG_NOT_OPTIMIZED)

        feedback_samples = [s for s in samples if s.user_feedback is not None]
        if feedback_samples:
            avg_feedback = sum(s.user_feedback for s in feedback_samples) / len(feedback_samples)
            if avg_feedback < -0.3:
                reasons.append(RecommendationReason.NEGATIVE_USER_FEEDBACK)

        failure_count = sum(1 for s in samples if not s.success)
        failure_rate = failure_count / len(samples) if samples else 0.0
        if failure_rate > 0.3:
            reasons.append(RecommendationReason.HIGH_FAILURE_RATE)

        return reasons
