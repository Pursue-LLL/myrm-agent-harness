"""Protocols for Skill Optimization Subsystem

Defines interfaces for data sources, storage, aggregators, and evaluators.

[INPUT]
- agent.skills.evolution.core.types::SkillMetrics (POS: Data types for skill evolution system.)
- backends.skills.types::SkillMetadata (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)
- agent.skills.evolution::SkillStore (POS: Skill evolution engine - Core of self-evolution system.)

[OUTPUT]
- SkillOptimizationStorage: class — Skill Optimization Storage
- SkillExecutionProvider: class — Skill Execution Provider
- StorageError: class — Storage Error
- StorageConnectionError: class — Storage Connection Error
- StorageTimeoutError: class — Storage Timeout Error

[POS]
Protocols for Skill Optimization Subsystem
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

# Import SkillMetrics from evolution system for funnel metrics integration
from myrm_agent_harness.agent.skills.evolution.core.types import SkillMetrics
from myrm_agent_harness.backends.skills.types import SkillMetadata

from .quality_calculator import SkillExecutionSample
from .types import (
    ABTestResult,
    ABTestStatus,
    AggregateDimension,
    ComparisonResult,
    GlobalQualityMetrics,
    OptimizationResult,
    SkillQualityAggregate,
    SkillQualityScore,
    SkillQualitySnapshot,
    SkillVersion,
    UserQualityAggregate,
)


class SkillOptimizationStorage(Protocol):
    """存储层抽象接口

    框架层定义接口, 业务层提供实现。
    支持多种后端: SQLAlchemy, MongoDB, Redis, 内存等。

    设计原则:
    1. 接口清晰: 所有方法明确定义输入输出
    2. 异步优先: 所有操作都是异步的
    3. 类型安全: 完整的类型提示
    4. 可测试性: 接口易于mock
    """

    # ==================== OptimizationRecord ====================

    async def save_optimization_record(self, record: OptimizationResult) -> None:
        """保存优化记录

        Args:
            record: 优化结果对象

        Raises:
            StorageError: 存储失败
        """
        ...

    async def get_optimization_record(self, skill_id: str) -> OptimizationResult | None:
        """获取最新优化记录

        Args:
            skill_id: Skill ID

        Returns:
            最新的优化记录, 不存在返回None
        """
        ...

    async def get_optimization_history(self, skill_id: str, limit: int = 10) -> list[OptimizationResult]:
        """获取优化历史

        Args:
            skill_id: Skill ID
            limit: 最大返回数量

        Returns:
            优化历史列表, 按时间倒序
        """
        ...

    async def get_recent_optimizations(self, hours: int = 24, limit: int = 100) -> list[OptimizationResult]:
        """获取最近优化记录

        Args:
            hours: 最近N小时
            limit: 最大返回数量

        Returns:
            最近优化记录列表
        """
        ...

    async def delete_old_optimizations(self, days: int = 90) -> int:
        """删除旧优化记录

        Args:
            days: 保留最近N天的记录

        Returns:
            删除的记录数
        """
        ...

    # ==================== ABTestResult ====================

    async def save_ab_test(self, result: ABTestResult) -> None:
        """保存A/B测试结果

        Args:
            result: A/B测试结果对象

        Raises:
            StorageError: 存储失败
        """
        ...

    async def get_ab_test(self, skill_id: str) -> ABTestResult | None:
        """获取正在运行的A/B测试

        Args:
            skill_id: Skill ID

        Returns:
            正在运行的A/B测试, 不存在返回None
        """
        ...

    async def get_running_ab_tests(self) -> list[ABTestResult]:
        """获取所有正在运行的A/B测试

        Returns:
            所有RUNNING状态的A/B测试列表
        """
        ...

    async def update_ab_test_status(self, skill_id: str, status: ABTestStatus, winner: str | None = None) -> None:
        """更新A/B测试状态

        Args:
            skill_id: Skill ID
            status: 新状态
            winner: 获胜版本("baseline" | "candidate")

        Raises:
            StorageError: 更新失败
        """
        ...

    async def increment_ab_test_sample_size(self, skill_id: str, increment: int = 1) -> int:
        """增加A/B测试样本数

        Args:
            skill_id: Skill ID
            increment: 增加量

        Returns:
            新的样本数
        """
        ...

    # ==================== SkillVersion ====================

    async def save_skill_version(
        self,
        skill_id: str,
        version: int,
        content: str,
        quality_score: SkillQualityScore | None = None,
        created_by: str = "llm",
        optimization_id: str | None = None,
        metadata: dict | None = None,
    ) -> SkillVersion:
        """保存Skill版本

        Args:
            skill_id: Skill ID
            version: 版本号
            content: Skill内容
            quality_score: 质量评分(可选)
            created_by: 创建方式("llm" | "manual" | "rollback")
            optimization_id: 关联的优化ID(可选)
            metadata: 额外元数据(可选)

        Returns:
            保存的SkillVersion对象

        Raises:
            StorageError: 存储失败
        """
        ...

    async def get_skill_version(self, skill_id: str, version: int) -> SkillVersion | None:
        """获取指定版本

        Args:
            skill_id: Skill ID
            version: 版本号

        Returns:
            SkillVersion对象, 不存在返回None
        """
        ...

    async def get_active_version(self, skill_id: str) -> SkillVersion | None:
        """获取当前激活版本

        Args:
            skill_id: Skill ID

        Returns:
            当前激活的SkillVersion, 不存在返回None
        """
        ...

    async def list_skill_versions(self, skill_id: str, limit: int = 50) -> list[SkillVersion]:
        """列出Skill所有版本

        Args:
            skill_id: Skill ID
            limit: 最大返回数量

        Returns:
            版本列表, 按版本号降序
        """
        ...

    async def activate_version(self, skill_id: str, version: int) -> SkillVersion:
        """激活指定版本(回滚)

        将指定版本设为active, 其他版本设为inactive。

        Args:
            skill_id: Skill ID
            version: 要激活的版本号

        Returns:
            激活的SkillVersion对象

        Raises:
            StorageError: 版本不存在或激活失败
        """
        ...

    async def delete_skill_versions(self, skill_id: str, keep_latest: int = 10) -> int:
        """删除旧版本

        保留最新N个版本和当前激活版本, 删除其余版本。

        Args:
            skill_id: Skill ID
            keep_latest: 保留最新N个版本

        Returns:
            删除的版本数
        """
        ...

    # ==================== SkillQualityHistory ====================

    async def save_quality_snapshot(self, skill_id: str, score: SkillQualityScore, version: int | None = None) -> None:
        """保存质量快照

        Args:
            skill_id: Skill ID
            score: 质量评分
            version: Skill版本号(可选)

        Raises:
            StorageError: 存储失败
        """
        ...

    async def get_quality_history(self, skill_id: str, days: int = 30) -> list[tuple[datetime, SkillQualityScore]]:
        """获取质量历史

        Args:
            skill_id: Skill ID
            days: 最近N天

        Returns:
            (时间戳, 质量评分)列表, 按时间倒序
        """
        ...

    async def get_latest_quality(self, skill_id: str) -> SkillQualityScore | None:
        """获取最新质量评分

        Args:
            skill_id: Skill ID

        Returns:
            最新质量评分, 不存在返回None
        """
        ...

    async def get_top_skills(self, limit: int = 10) -> list[tuple[str, SkillQualityScore]]:
        """获取质量最高的skill

        Args:
            limit: 最大返回数量

        Returns:
            (skill_id, 质量评分)列表, 按评分降序
        """
        ...

    async def get_bottom_skills(self, limit: int = 10) -> list[tuple[str, SkillQualityScore]]:
        """获取质量最低的skill

        Args:
            limit: 最大返回数量

        Returns:
            (skill_id, 质量评分)列表, 按评分升序
        """
        ...

    # ==================== Health Check ====================

    async def health_check(self) -> dict[str, bool | str]:
        """健康检查

        Returns:
            健康状态字典, 包含:
            - healthy: bool - 总体健康状态
            - storage_type: str - 存储类型
            - writable: bool - 是否可写
            - readable: bool - 是否可读
        """
        ...


class SkillExecutionProvider(Protocol):
    """Skill执行事件提供者接口

    框架层定义接口, 业务层提供实现。
    从各种事件源(EventLog, metrics, logs)查询skill执行数据。

    设计原则:
    1. 数据源无关: 可以是EventLog, Prometheus, files, etc.
    2. 流式接口: 支持大规模数据查询
    3. 时间范围: 所有查询都支持时间过滤
    """

    async def get_skill_executions(
        self, skill_id: str, days: int = 7, session_id: str | None = None
    ) -> list[SkillExecutionSample]:
        """获取skill执行样本

        Args:
            skill_id: Skill ID
            days: 最近N天的数据
            session_id: 可选的session过滤

        Returns:
            执行样本列表
        """
        ...

    async def get_all_skill_ids(self) -> list[str]:
        """获取所有有执行记录的skill ID

        Returns:
            Skill ID列表
        """
        ...

    async def count_executions(self, skill_id: str, days: int = 7) -> int:
        """统计执行次数

        Args:
            skill_id: Skill ID
            days: 最近N天

        Returns:
            执行次数
        """
        ...

    async def get_skill_metadata(self, skill_id: str) -> SkillMetadata | None:
        """获取skill元数据

        Args:
            skill_id: Skill ID

        Returns:
            SkillMetadata对象, 如果skill不存在则返回None
        """
        ...

    async def get_skill_content(self, skill_id: str) -> str | None:
        """获取skill源码内容 (SKILL.md)

        Args:
            skill_id: Skill ID

        Returns:
            Skill源码内容, 如果不存在返回None
        """
        ...


class StorageError(Exception):
    """存储层错误基类"""

    pass


class StorageConnectionError(StorageError):
    """存储连接错误"""

    pass


class StorageTimeoutError(StorageError):
    """存储操作超时"""

    pass


class SkillMetricsProvider(Protocol):
    """Skill Metrics Provider Protocol (Optional Integration)

    Optional protocol for integrating skill funnel metrics from evolution system.
    Provides detailed usage tracking (selections, applications, completions, successes).

    This is an optional enhancement - if not provided, optimization system works
    with basic quality scores only. When provided, enables funnel analysis in
    the Optimization Dashboard (like OpenSpace).

    Design Principles:
    - Optional: Optimizer works without metrics provider
    - Loose coupling: Framework doesn't depend on evolution system directly
    - Single source of truth: Metrics only stored in evolution system
    - Read-only: Provider only reads metrics, doesn't modify them

    Usage Example:
        ```python
        # Business layer implementation
        from myrm_agent_harness.agent.skills.evolution import SkillStore

        class EvolutionMetricsProvider:
            def __init__(self, store: SkillStore):
                self.store = store

            async def get_skill_metrics(self, skill_id: str) -> SkillMetrics | None:
                record = self.store.get_skill_by_id(skill_id)
                return record.metrics if record else None

        # Pass to optimization system
        provider = EvolutionMetricsProvider(evolution_store)
        scheduler = OptimizationScheduler(..., metrics_provider=provider)
        ```
    """

    async def get_skill_metrics(self, skill_id: str) -> SkillMetrics | None:
        """Get skill funnel metrics from evolution system

        Args:
            skill_id: Skill identifier

        Returns:
            SkillMetrics with funnel data (total_selections, applied_count,
            completed_count, success_count) or None if not found

        Example:
            ```python
            metrics = await provider.get_skill_metrics("pdf-generator")
            if metrics:
                print(f"Fallback rate: {metrics.fallback_rate:.1%}")
                print(f"Success rate: {metrics.effective_rate:.1%}")
            ```
        """
        ...


class SkillQualityAggregator(Protocol):
    """Skill Quality Aggregation Protocol

    Framework-level abstract interface for aggregating skill quality across
    time/users/dimensions. Designed for framework independence and reusability.

    Design Principles:
    1. Framework Independence: No business-specific logic (user_id, tenant_id agnostic)
    2. Protocol-Based: Supports multiple implementations (InMemory, SQL, Redis, Streaming)
    3. Async First: All operations are async for performance
    4. Type Safe: Complete type hints for IDE support
    5. Out-of-the-Box: InMemoryAggregator provides default implementation

    Analogies:
    - Similar to SkillOptimizationStorage Protocol (framework defines, business implements)
    - Like LangChain's BaseRetriever Protocol (abstraction layer)

    Implementations:
    - InMemoryAggregator: Framework layer (default, local/tauri/dev)
    - StreamingAggregator: Framework layer (real-time incremental)
    - UniversalAggregator: Framework layer (universal aggregator using DataSource)

    New Architecture (DataSource Pattern):
    Framework provides UniversalAggregator that depends on SkillQualityDataSource Protocol.
    Business layer implements DataSource adapters:
    - SQLSkillQualityDataSource: SQL queries (production)

    Usage Example:
        ```python
        # Framework layer (out-of-the-box)
        from myrm_agent_harness.agent.skills.optimization import InMemoryAggregator

        aggregator = InMemoryAggregator(storage)
        metrics = await aggregator.get_global_metrics()

        # Business layer (production with DataSource Pattern)
        from myrm_agent_harness.agent.skills.optimization import UniversalAggregator

        data_source = ProductSkillQualityDataSource(db_session)
        aggregator = UniversalAggregator(data_source)
        metrics = await aggregator.get_global_metrics()
        ```
    """

    async def aggregate_by_skill(
        self, skill_id: str | None = None, time_range_days: int = 30
    ) -> list[SkillQualityAggregate]:
        """Aggregate quality metrics by skill

        Args:
            skill_id: Optional filter for specific skill, None returns all skills
            time_range_days: Time window for aggregation (default 30 days)

        Returns:
            List of SkillQualityAggregate sorted by quality score descending

        Example:
            ```python
            all_skills = await aggregator.aggregate_by_skill()
            one_skill = await aggregator.aggregate_by_skill("pdf-generator", days=7)
            ```
        """
        ...

    async def aggregate_by_user(self, time_range_days: int = 30) -> list[UserQualityAggregate]:
        """Aggregate quality metrics by user

        Args:
            user_id: Optional filter for specific user, None returns all users
            time_range_days: Time window for aggregation (default 30 days)

        Returns:
            List of UserQualityAggregate sorted by quality score descending

        Example:
            ```python
            all_users = await aggregator.aggregate_by_user()
            one_user = await aggregator.aggregate_by_user("user-123", days=7)
            ```
        """
        ...

    async def aggregate_by_dimension(
        self, dimension: AggregateDimension, time_range_days: int = 30
    ) -> dict[str, SkillQualityAggregate]:
        """Aggregate quality metrics by custom dimension

        Args:
            dimension: Aggregation dimension (skill_type, user_tier, time_of_day, etc.)
            time_range_days: Time window for aggregation (default 30 days)

        Returns:
            Dictionary mapping dimension value to aggregate

        Example:
            ```python
            by_type = await aggregator.aggregate_by_dimension(AggregateDimension.SKILL_TYPE)
            by_hour = await aggregator.aggregate_by_dimension(AggregateDimension.TIME_OF_DAY)
            ```
        """
        ...

    async def get_global_metrics(self, time_range_days: int = 30) -> GlobalQualityMetrics:
        """Get global quality metrics across all skills/users

        Args:
            time_range_days: Time window for aggregation (default 30 days)

        Returns:
            GlobalQualityMetrics with system-wide statistics

        Example:
            ```python
            metrics = await aggregator.get_global_metrics()
            print(f"Avg quality: {metrics.avg_quality_score:.2f}")
            print(f"Total skills: {metrics.total_skills}")
            ```
        """
        ...

    async def compare(
        self, before_range_days: int, after_range_days: int, skill_id: str | None = None
    ) -> list[ComparisonResult]:
        """Compare quality metrics across two time periods

        Args:
            before_range_days: Days ago for "before" snapshot
            after_range_days: Days ago for "after" snapshot (0 = now)
            skill_id: Optional filter for specific skill

        Returns:
            List of ComparisonResult showing before/after delta

        Example:
            ```python
            # Compare last 7 days vs previous 7 days
            results = await aggregator.compare(before_range_days=14, after_range_days=7)

            # Compare specific skill optimization impact
            before_opt = await aggregator.compare(
                before_range_days=30,
                after_range_days=0,
                skill_id="pdf-generator"
            )
            ```
        """
        ...

    async def get_quality_percentiles(self, skill_id: str | None = None, time_range_days: int = 30) -> dict[str, float]:
        """Get quality score percentiles (P50/P90/P95/P99)

        Args:
            skill_id: Optional filter for specific skill
            time_range_days: Time window for calculation

        Returns:
            Dictionary with keys: p50, p90, p95, p99

        Example:
            ```python
            percentiles = await aggregator.get_quality_percentiles()
            print(f"P90: {percentiles['p90']:.2f}")
            print(f"P99: {percentiles['p99']:.2f}")
            ```
        """
        ...


class SkillQualityDataSource(Protocol):
    """Data source interface for UniversalAggregator

    Provides raw records and optional pre-aggregated data for quality aggregation.
    Business layer implements this protocol with concrete storage backends (SQL/Redis/etc.).

    Usage:
        ```python
        class SQLSkillQualityDataSource:
            async def query_raw_records(self, skill_id=None, time_range_days=30, filters=None):
                ...
            async def query_aggregated(self, group_by, time_range_days=30, filters=None):
                return []  # fallback to raw records
        ```
    """

    async def query_raw_records(
        self, skill_id: str | None = None, time_range_days: int = 30, filters: dict[str, str] | None = None
    ) -> list[SkillQualitySnapshot]: ...

    async def query_aggregated(
        self, group_by: str, time_range_days: int = 30, filters: dict[str, str] | None = None
    ) -> list[dict[str, float]]: ...
