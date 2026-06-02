"""Skill Optimization Types

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- enum.Enum (POS: Python标准枚举基类)
- typing.Protocol (POS: Python协议类型)
- dataclasses.dataclass (POS: Python数据类装饰器)
- contextlib.AsyncContextManager (POS: Python异步上下文管理器)

[OUTPUT]
- SkillType: Skill类型枚举 (PREBUILT/USER/WORKSPACE)
- LockProvider: 分布式锁提供者协议
- SkillQualityScore: 5维Skill质量评分
- SecurityValidationResult: 安全验证结果
- OptimizationStatus: 优化状态枚举
- ABTestStatus: A/B测试状态枚举
- OptimizationResult: 优化结果
- ABTestResult: A/B测试结果
- SkillQualityAggregate: 单个skill的聚合统计数据
- UserQualityAggregate: 单个用户的聚合统计数据
- GlobalQualityMetrics: 全局质量指标
- QualityPercentiles: 质量分数百分位数
- ComparisonResult: 对比分析结果
- PredictionResult: 预测分析结果
- AnomalyReport: 异常检测报告
- RootCause: 根因分析结果
- AggregateDimension: 聚合维度枚举

[POS]
Skill optimization system core type definitions. Provides type-safe data structures and protocol interfaces.

"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from myrm_agent_harness.agent.skills.evolution.types import SkillMetrics


class SkillType(StrEnum):
    """Skill类型枚举

    用于区分skill的存储范围和并发控制需求：
    - PREBUILT: 全局共享，需要跨进程锁 (Cross-Process Lock)
    - USER: per-user隔离，不需要锁
    - WORKSPACE: per-workspace隔离，不需要锁
    """

    PREBUILT = "prebuilt"
    USER = "user"
    WORKSPACE = "workspace"


class LockProvider(Protocol):
    """并发锁提供者协议 (Concurrency Lock Provider)

    针对单机架构提供跨多进程、多线程的并发访问保护。
    框架提供协议定义，单机默认实现通常为 FileLock。
    """

    async def acquire(self, key: str, timeout: float = 30.0) -> AbstractAsyncContextManager[None]:
        """获取并发锁

        Args:
            key: 锁的唯一标识（如skill:opt:skill_name）
            timeout: 锁超时时间（秒）

        Returns:
            异步上下文管理器

        Raises:
            LockAcquisitionError: 获取锁失败
        """
        ...


@dataclass
class SkillQualityScore:
    """5维Skill质量评分 + 成本追踪

    综合评估Skill质量的5个关键指标：
    1. success_rate: 成功率（0-1）
    2. token_efficiency: Token效率（tokens per call的倒数归一化）
    3. execution_time: 执行时间（秒的倒数归一化）
    4. user_satisfaction: 用户满意度（0-1，基于点赞/点踩 + 隐式反馈）
    5. call_frequency: 调用频率（归一化）

    成本追踪字段（新增）：
    - prompt_tokens: LLM调用的输入token数
    - completion_tokens: LLM调用的输出token数
    - total_tokens: 总token数（prompt + completion）
    - llm_cost_usd: LLM调用成本（美元）
    """

    success_rate: float  # 0-1
    token_efficiency: float  # 0-1
    execution_time: float  # 0-1 (normalized inverse)
    user_satisfaction: float  # 0-1
    call_frequency: float  # 0-1 (normalized)

    # 成本追踪字段
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    llm_cost_usd: float = 0.0

    # Funnel metrics (optional, from evolution system)
    funnel_metrics: SkillMetrics | None = None

    @property
    def overall_score(self) -> float:
        """综合评分（加权平均）"""
        weights = {
            "success_rate": 0.3,
            "token_efficiency": 0.2,
            "execution_time": 0.2,
            "user_satisfaction": 0.2,
            "call_frequency": 0.1,
        }
        return (
            self.success_rate * weights["success_rate"]
            + self.token_efficiency * weights["token_efficiency"]
            + self.execution_time * weights["execution_time"]
            + self.user_satisfaction * weights["user_satisfaction"]
            + self.call_frequency * weights["call_frequency"]
        )


@dataclass
class SecurityValidationResult:
    """安全验证结果"""

    passed: bool
    issues: list[str]  # 安全问题列表

    @property
    def is_safe(self) -> bool:
        """是否安全"""
        return self.passed and len(self.issues) == 0


class OptimizationStatus(StrEnum):
    """优化状态枚举"""

    PENDING = "pending" # 等待中
    IN_PROGRESS = "in_progress" # 进行中
    TESTING = "testing" # A/B测试中
    COMPLETED = "completed" # 已完成
    FAILED = "failed" # 失败
    ROLLED_BACK = "rolled_back" # 已回滚


class ABTestStatus(StrEnum):
    """A/B测试状态枚举"""

    RUNNING = "running" # 运行中
    BASELINE_WIN = "baseline_win" # 基线版本胜出
    CANDIDATE_WIN = "candidate_win" # 候选版本胜出
    NO_DIFFERENCE = "no_difference" # 无显著差异
    FAILED = "failed" # 测试失败
    STOPPED = "stopped" # 提前停止


@dataclass
class OptimizationResult:
    """优化结果"""

    skill_id: str
    skill_type: SkillType
    baseline_score: SkillQualityScore
    optimized_content: str
    security_validation: SecurityValidationResult
    status: OptimizationStatus
    started_at: datetime
    completed_at: datetime | None = None
    error: str | None = None
    version: int | None = None  # 优化后生成的版本号（如果已保存）


@dataclass
class SkillVersion:
    """Skill版本

    记录skill的每个版本，支持版本回滚。
    """

    skill_id: str
    version: int  # 版本号，从1开始递增
    content: str  # Skill内容
    quality_score: SkillQualityScore | None  # 该版本的质量评分（可能未评估）
    created_at: datetime
    created_by: str  # "llm" | "manual" | "rollback"
    optimization_id: str | None = None  # 关联的优化ID（如果是LLM优化产生的）
    is_active: bool = False  # 是否为当前激活版本
    metadata: dict | None = None  # 额外元数据


@dataclass
class ABTestResult:
    """A/B测试结果"""

    skill_id: str
    baseline_version: int
    candidate_version: int
    baseline_score: SkillQualityScore
    candidate_score: SkillQualityScore
    sample_size: int
    status: ABTestStatus
    started_at: datetime
    completed_at: datetime | None = None
    winner: str | None = None  # "baseline" | "candidate" | None


class LockAcquisitionError(Exception):
    """获取锁失败异常"""

    pass


class OptimizationError(Exception):
    """优化失败异常"""

    pass


class SecurityError(Exception):
    """安全验证失败异常"""

    pass


class VersionConflictError(Exception):
    """版本冲突异常"""

    pass


class AggregateDimension(StrEnum):
    """聚合维度枚举"""

    SKILL = "skill"
    USER = "user"
    SKILL_TYPE = "skill_type"
    USER_TIER = "user_tier"
    TIME_OF_DAY = "time_of_day"
    DAY_OF_WEEK = "day_of_week"
    REGION = "region"


@dataclass
class SkillQualityAggregate:
    """单个skill的聚合统计数据

    跨时间范围/用户聚合后的skill质量统计，用于分析单个skill的整体表现。

    Fields:
        skill_id: Skill的唯一标识符
        sample_count: 样本数量（参与聚合的执行记录数）
        avg_quality_score: 平均质量分数（0-1，综合5维指标的加权平均）
        quality_std: 质量分数的标准差（衡量质量稳定性）
        avg_success_rate: 平均成功率（0-1，成功执行的比例）
        avg_token_efficiency: 平均Token效率（0-1，归一化后的Token使用效率）
        avg_execution_time: 平均执行时间（秒）
        avg_user_satisfaction: 平均用户满意度（0-1，基于显式/隐式反馈）
        total_executions: 总执行次数（与sample_count可能不同，因为可能有过滤）
        user_count: 使用该skill的用户数量
        optimization_count: 该skill被优化的次数
        last_optimization: 最近一次优化的时间戳
        time_range_start: 统计时间范围起点
        time_range_end: 统计时间范围终点

    Example:
        ```python
        aggregate = SkillQualityAggregate(
            skill_id="web_search",
            sample_count=1000,
            avg_quality_score=0.85,
            quality_std=0.12,
            avg_success_rate=0.92,
            avg_token_efficiency=0.78,
            avg_execution_time=2.5,
            avg_user_satisfaction=0.88,
            total_executions=1000,
            user_count=50,
            optimization_count=3)
        ```
    """

    skill_id: str
    sample_count: int
    avg_quality_score: float
    quality_std: float
    avg_success_rate: float
    avg_token_efficiency: float
    avg_execution_time: float
    avg_user_satisfaction: float
    total_executions: int
    user_count: int
    optimization_count: int
    last_optimization: datetime | None = None
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None


@dataclass
class UserQualityAggregate:
    """单个用户的聚合统计数据

    单个用户在所有skill上的整体表现统计，用于分析用户行为和偏好。

    Fields:
        user_id: 用户的唯一标识符
        sample_count: 样本数量（参与聚合的执行记录数）
        avg_quality_score: 平均质量分数（0-1，该用户所有skill执行的平均质量）
        unique_skills_used: 使用的唯一技能数量（该用户使用过的不同skill总数）
        total_executions: 总执行次数（该用户的总调用次数）
        favorite_skill: 最常用的skill ID（调用次数最多的skill）
        time_range_start: 统计时间范围起点
        time_range_end: 统计时间范围终点

    Example:
        ```python
        aggregate = UserQualityAggregate(
            user_id="user_123",
            sample_count=500,
            avg_quality_score=0.80,
            unique_skills_used=15,
            total_executions=500,
            favorite_skill="web_search")
        ```
    """

    user_id: str
    sample_count: int
    avg_quality_score: float
    unique_skills_used: int
    total_executions: int
    favorite_skill: str | None = None
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None


@dataclass
class GlobalQualityMetrics:
    """全局质量指标

    整个系统的全局统计，用于监控系统整体健康度和趋势。

    Fields:
        total_skills: 系统中的技能总数（所有已注册的skill，唯一计数）
        total_users: 用户总数（活跃使用系统的用户总数，唯一计数）
        total_executions: 总执行次数（所有skill的总调用次数，可重复计数）
        avg_quality_score: 平均质量分数（0-1，全局平均质量）
        median_quality_score: 中位数质量分数（0-1，更稳健的中心趋势指标）
        quality_std: 质量分数的标准差（衡量全局质量的稳定性）
        top_skills_count: 顶级技能数量（质量分数 >= 0.8 的skill数量）
        bottom_skills_count: 底部技能数量（质量分数 < 0.5 的skill数量）
        optimization_rate: 优化率（0-1，已优化skill占总skill的比例）
        calculated_at: 指标计算时间戳

    Example:
        ```python
        metrics = GlobalQualityMetrics(
            total_skills=100,
            total_users=500,
            total_executions=50000,
            avg_quality_score=0.75,
            median_quality_score=0.78,
            quality_std=0.15,
            top_skills_count=40,
            bottom_skills_count=10,
            optimization_rate=0.60,
            calculated_at=datetime.now())
        ```
    """

    total_skills: int
    total_users: int
    total_executions: int
    avg_quality_score: float
    median_quality_score: float
    quality_std: float
    top_skills_count: int
    bottom_skills_count: int
    optimization_rate: float
    calculated_at: datetime


@dataclass
class QualityPercentiles:
    """质量分数百分位数

    用于分析质量分数的分布特征，提供更细粒度的统计视图。

    Fields:
        p25: 第25百分位（Q1，下四分位数）
        p50: 第50百分位（中位数）
        p75: 第75百分位（Q3，上四分位数）
        p90: 第90百分位（高分位数）
        p95: 第95百分位（极高分位数）
        p99: 第99百分位（接近最大值）

    Example:
        ```python
        percentiles = QualityPercentiles(
            p25=0.60,
            p50=0.75,
            p75=0.85,
            p90=0.92,
            p95=0.96,
            p99=0.99)
        ```
    """

    p25: float
    p50: float
    p75: float
    p90: float
    p95: float
    p99: float


@dataclass
class ComparisonResult:
    """对比分析结果

    支持优化前后对比、版本对比、用户间对比等场景。提供完整的5维质量指标对比和统计显著性验证。

    Fields:
        before: 对比前的聚合数据
        after: 对比后的聚合数据
        delta_quality: 质量分数变化量
        delta_success_rate: 成功率变化量
        delta_token_efficiency: Token效率变化量
        delta_execution_time: 执行时间变化量（秒）
        delta_user_satisfaction: 用户满意度变化量
        improvement_pct: 改进百分比（基于质量分数）
        is_statistically_significant: 是否具有统计显著性
        p_value: p值（<0.05表示显著），None表示样本量不足
        compared_at: 对比时间戳

    Example:
        ```python
        result = ComparisonResult(
            before=before_aggregate,
            after=after_aggregate,
            delta_quality=0.15,
            delta_success_rate=0.10,
            delta_token_efficiency=0.08,
            delta_execution_time=-0.5,
            delta_user_satisfaction=0.12,
            improvement_pct=18.75,
            is_statistically_significant=True,
            p_value=0.003,
            compared_at=datetime.now())
        ```
    """

    before: SkillQualityAggregate | UserQualityAggregate
    after: SkillQualityAggregate | UserQualityAggregate
    delta_quality: float
    delta_success_rate: float
    delta_token_efficiency: float
    delta_execution_time: float
    delta_user_satisfaction: float
    improvement_pct: float
    is_statistically_significant: bool
    p_value: float | None
    compared_at: datetime


@dataclass
class PredictionResult:
    """预测分析结果

    基于历史数据预测未来质量趋势。
    """

    skill_id: str
    current_quality: float
    predicted_quality: float
    trend: str
    confidence: float
    forecast_days: int
    predicted_at: datetime


@dataclass
class RootCause:
    """根因分析结果

    识别质量下降的主要原因。
    """

    primary_cause: str
    token_delta: float
    duration_delta: float
    error_rate_delta: float
    details: dict | None = None


@dataclass
class AnomalyReport:
    """异常检测报告

    识别质量突变的异常时间点。
    """

    skill_id: str
    timestamp: datetime
    quality_score: float
    z_score: float
    root_cause: RootCause
    impact_user_count: int
    severity: str
    detected_at: datetime


@dataclass
class SkillQualitySnapshot:
    """Raw quality record from a single observation."""

    id: str
    skill_id: str
    recorded_at: datetime
    overall_score: float
    success_rate: float
    token_efficiency: float
    execution_time: float
    user_satisfaction: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    llm_cost_usd: float = 0.0
