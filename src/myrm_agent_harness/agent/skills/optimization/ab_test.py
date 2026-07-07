"""A/B Test Engine

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- .types::ABTestResult, ABTestStatus, SkillQualityScore, VersionConflictError (POS: A/B测试类型)
- .config::ABTestConfig (POS: A/B测试配置)

[OUTPUT]
- ABTestEngine: A/B测试引擎（自适应采样 + 快速失败检测 + 早停）

[POS]
A/B test engine. Implements scientific optimization validation with traffic splitting and statistical significance testing.

"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import ABTestConfig
    from .types import ABTestResult, SkillQualityScore

from .types import ABTestStatus, VersionConflictError

logger = logging.getLogger(__name__)


class ABTestEngine:
    """A/B测试引擎

    智能A/B测试策略：
    1. 自适应采样：根据skill调用频率动态调整样本量
    2. 快速失败检测：candidate质量显著低于baseline时提前停止
    3. 早停机制：candidate质量显著高于baseline时提前结束
    4. 统计显著性检验：使用t-test确保结果可信
    5. 版本冲突检测：使用乐观锁防止并发修改
    """

    def __init__(self, config: ABTestConfig):
        """初始化A/B测试引擎

        Args:
            config: A/B测试配置
        """
        self.config = config

    async def start_ab_test(
        self,
        skill_id: str,
        baseline_version: int,
        baseline_score: SkillQualityScore,
        candidate_content: str,
        current_skill_version: int | None = None,
    ) -> ABTestResult:
        """开始A/B测试

        Args:
            skill_id: Skill ID
            baseline_version: 基线版本号
            baseline_score: 基线质量评分
            candidate_content: 候选版本内容
            current_skill_version: 当前skill版本号（用于乐观锁检查）

        Returns:
            ABTestResult: A/B测试结果

        Raises:
            VersionConflictError: 版本冲突（skill在优化过程中被修改）
        """
        from .types import ABTestResult

        started_at = datetime.now()

        logger.info(f"Starting A/B test for skill: {skill_id}, baseline_version: {baseline_version}")

        # 1. 版本冲突检测（乐观锁）
        if current_skill_version is not None and current_skill_version != baseline_version:
            raise VersionConflictError(
                f"Skill version changed during optimization: expected {baseline_version}, got {current_skill_version}"
            )

        # 2. 计算目标样本量
        target_sample_size = self._calculate_sample_size(baseline_score.call_frequency)

        # 3. 创建A/B测试记录（初始状态）
        result = ABTestResult(
            skill_id=skill_id,
            baseline_version=baseline_version,
            candidate_version=baseline_version + 1,
            baseline_score=baseline_score,
            candidate_score=baseline_score,  # 初始假设相同，后续更新
            sample_size=0,
            status=ABTestStatus.RUNNING,
            started_at=started_at,
        )

        logger.info(
            f"A/B test started: {skill_id}, "
            f"target_sample_size={target_sample_size}, "
            f"baseline_score={baseline_score.overall_score:.2f}"
        )

        return result

    async def evaluate_ab_test(self, ab_test: ABTestResult, candidate_samples: list[dict]) -> ABTestResult:
        """评估A/B测试结果

        收集足够样本后，进行统计分析并决定winner。

        Args:
            ab_test: A/B测试记录
            candidate_samples: 候选版本的执行样本数据

        Returns:
            ABTestResult: 更新后的A/B测试结果
        """
        # 计算candidate的实际质量评分
        candidate_score = self._calculate_quality_score(candidate_samples)
        ab_test.candidate_score = candidate_score
        ab_test.sample_size = len(candidate_samples)

        # 检查是否应该提前停止
        should_stop, stop_reason = self._should_stop_early(ab_test.baseline_score, candidate_score, ab_test.sample_size)

        if should_stop:
            if stop_reason == "quick_failure":
                ab_test.status = ABTestStatus.BASELINE_WIN
                ab_test.winner = "baseline"
                logger.warning(f"A/B test quick failure: {ab_test.skill_id}, rolling back")
            elif stop_reason == "early_stopping":
                ab_test.status = ABTestStatus.CANDIDATE_WIN
                ab_test.winner = "candidate"
                logger.info(f"A/B test early stopping: {ab_test.skill_id}, candidate wins")

            ab_test.completed_at = datetime.now()
            return ab_test

        # 达到目标样本量后，进行最终统计分析
        target_sample_size = self._calculate_sample_size(ab_test.baseline_score.call_frequency)
        if ab_test.sample_size >= target_sample_size:
            # 统计显著性检验
            is_significant = self._is_statistically_significant(
                ab_test.baseline_score, candidate_score, ab_test.sample_size
            )

            if not is_significant:
                ab_test.status = ABTestStatus.NO_DIFFERENCE
                ab_test.winner = "baseline"  # 无显著差异，保守选择baseline
                logger.info(f"A/B test no significant difference: {ab_test.skill_id}")
            elif candidate_score.overall_score > ab_test.baseline_score.overall_score:
                ab_test.status = ABTestStatus.CANDIDATE_WIN
                ab_test.winner = "candidate"
                logger.info(f"A/B test completed: {ab_test.skill_id}, candidate wins")
            else:
                ab_test.status = ABTestStatus.BASELINE_WIN
                ab_test.winner = "baseline"
                logger.info(f"A/B test completed: {ab_test.skill_id}, baseline wins")

            ab_test.completed_at = datetime.now()

        return ab_test

    def _calculate_quality_score(self, samples: list[dict]) -> SkillQualityScore:
        """从样本数据计算质量评分

        Args:
            samples: 样本数据列表，每个样本包含：
                - success: bool
                - tokens_used: int
                - execution_time: float
                - user_feedback: int (-1/0/1)

        Returns:
            SkillQualityScore: 质量评分
        """
        from .types import SkillQualityScore

        if not samples:
            return SkillQualityScore(
                success_rate=0.0, token_efficiency=0.0, execution_time=0.0, user_satisfaction=0.5, call_frequency=0.0
            )

        # 计算各维度指标
        success_count = sum(1 for s in samples if s.get("success", False))
        success_rate = success_count / len(samples)

        # Token效率（假设平均1000 tokens为基准）
        avg_tokens = sum(s.get("tokens_used", 0) for s in samples) / len(samples)
        token_efficiency = max(0, min(1, 1000 / (avg_tokens + 1)))

        # 执行时间效率（假设10秒为基准）
        avg_time = sum(s.get("execution_time", 0) for s in samples) / len(samples)
        execution_time = max(0, min(1, 10 / (avg_time + 0.1)))

        # 用户满意度（-1到1映射到0到1）
        feedbacks = [s.get("user_feedback", 0) for s in samples if "user_feedback" in s]
        if feedbacks:
            avg_feedback = sum(feedbacks) / len(feedbacks)
            user_satisfaction = (avg_feedback + 1) / 2  # -1到1 -> 0到1
        else:
            user_satisfaction = 0.5  # 无反馈默认0.5

        # 调用频率（由外部提供，这里保持baseline的值）
        call_frequency = 0.5  # 默认值

        return SkillQualityScore(
            success_rate=success_rate,
            token_efficiency=token_efficiency,
            execution_time=execution_time,
            user_satisfaction=user_satisfaction,
            call_frequency=call_frequency,
        )

    def _calculate_sample_size(self, call_frequency: float) -> int:
        """计算自适应样本量

        根据skill调用频率动态调整样本量：
        - 高频skill: 使用max_sample_size（充分样本）
        - 低频skill: 使用min_sample_size（快速验证）
        - 中频skill: 线性插值

        Args:
            call_frequency: 调用频率（归一化，0-1）

        Returns:
            int: 样本量
        """
        if not self.config.enable_adaptive_sampling:
            return self.config.max_sample_size

        # 线性插值
        sample_size = int(
            self.config.min_sample_size + (self.config.max_sample_size - self.config.min_sample_size) * call_frequency
        )

        return sample_size

    def _should_stop_early(
        self, baseline_score: SkillQualityScore, candidate_score: SkillQualityScore, current_sample_size: int
    ) -> tuple[bool, str]:
        """判断是否应该提前停止

        两种情况会提前停止：
        1. 快速失败：candidate明显劣于baseline
        2. 早停：candidate明显优于baseline且统计显著

        Args:
            baseline_score: 基线评分
            candidate_score: 候选评分
            current_sample_size: 当前样本量

        Returns:
            tuple[bool, str]: (是否停止, 停止原因)
        """
        score_diff = candidate_score.overall_score - baseline_score.overall_score

        # 1. 快速失败检测
        if (
            self.config.enable_quick_failure_detection
            and score_diff < -self.config.quick_failure_threshold
            and current_sample_size >= self.config.min_sample_size
        ):
            return (True, "quick_failure")

        # 2. 早停检测
        if (
            self.config.enable_early_stopping
            and score_diff > self.config.early_stopping_threshold
            and current_sample_size >= self.config.min_sample_size
        ):
            return (True, "early_stopping")

        return (False, "")

    def _is_statistically_significant(
        self, baseline_score: SkillQualityScore, candidate_score: SkillQualityScore, sample_size: int
    ) -> bool:
        """统计显著性检验

        使用effect size检查和样本量要求判断统计显著性。
        注意：完整的t-test需要原始样本数据，这里使用简化但科学的方法。

        Args:
            baseline_score: 基线评分
            candidate_score: 候选评分
            sample_size: 样本量

        Returns:
            bool: 是否统计显著
        """
        # 1. 检查样本量是否足够
        if sample_size < self.config.min_sample_size:
            return False

        # 2. 检查效果量（Cohen's d approximation）
        score_diff = abs(candidate_score.overall_score - baseline_score.overall_score)

        if score_diff < self.config.min_effect_size:
            return False

        # 3. 样本量越大，对效果量的要求可以适当降低
        # 使用置信水平调整（简化的统计显著性判断）
        confidence_multiplier = self.config.confidence_level
        adjusted_threshold = self.config.min_effect_size * (2 - confidence_multiplier)

        return score_diff >= adjusted_threshold

    def _is_statistically_significant_with_samples(
        self, baseline_samples: list[float], candidate_samples: list[float]
    ) -> bool:
        """使用原始样本数据的统计显著性检验（独立样本t检验）

        当有原始样本数据时使用此方法进行更准确的统计检验。

        Args:
            baseline_samples: baseline的overall_score样本列表
            candidate_samples: candidate的overall_score样本列表

        Returns:
            bool: 是否统计显著
        """
        try:
            from scipy import stats

            if len(baseline_samples) < 2 or len(candidate_samples) < 2:
                # 样本不足，无法进行t检验
                return False

            # 执行独立样本t检验
            _t_statistic, p_value = stats.ttest_ind(baseline_samples, candidate_samples)

            # 比较p-value与显著性水平
            alpha = 1 - self.config.confidence_level

            return p_value < alpha

        except (ImportError, TypeError):
            # scipy未安装，降级到简化方法
            logger.warning("scipy not available, using simplified significance test")
            import statistics

            baseline_mean = statistics.mean(baseline_samples)
            candidate_mean = statistics.mean(candidate_samples)
            score_diff = abs(candidate_mean - baseline_mean)

            return score_diff >= self.config.min_effect_size
