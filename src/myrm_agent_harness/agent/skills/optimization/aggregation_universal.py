"""Universal Skill Quality Aggregator

[INPUT]
- .protocols.SkillQualityAggregator (POS: Aggregation Protocol)
- .protocols.SkillQualityDataSource (POS: DataSource Protocol)
- .math_utils (POS: sample_std, percentile)
- .types.* (POS: Aggregate data types)

[OUTPUT]
- UniversalAggregator: Universal aggregation (depends on DataSource Protocol)

[POS]
Framework-layer universal aggregator decoupled from business layer via DataSource Protocol.
Supports any DataSource backend (SQL/Redis/File/API) with dependency inversion.
Prefers pre-aggregated data (fast path), falls back to raw records (universal path).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .math_utils import percentile as calc_percentile
from .math_utils import sample_std
from .protocols import SkillQualityAggregator, SkillQualityDataSource
from .types import (
    AggregateDimension,
    ComparisonResult,
    GlobalQualityMetrics,
    SkillQualityAggregate,
    UserQualityAggregate,
)

if TYPE_CHECKING:
    from .types import SkillQualitySnapshot

logger = logging.getLogger(__name__)


class UniversalAggregator(SkillQualityAggregator):
    """Universal Skill Quality Aggregator

    Framework-level universal aggregator implementation that works with any DataSource.
    Decouples aggregation logic (framework layer) from data storage (business layer).

    Design Principles:
    1. Dependency Inversion: Depends on DataSource Protocol, not concrete implementation
    2. Framework Independence: No business logic, no DB dependencies
    3. Performance Optimized: Prefers pre-aggregated data, falls back to raw records
    4. Single Responsibility: Only aggregation logic, data query delegated to DataSource

    Features:
    - Works with any DataSource backend (SQL/Redis/File/API)
    - Automatic optimization: uses pre-aggregation when available
    - Full aggregation capability: GroupBy, Avg, Percentile, etc.
    - Type-safe: Complete type hints for IDE support

    Performance:
    - With pre-aggregation: O(M) where M is pre-aggregated groups count
    - Without pre-aggregation: O(N) where N is raw records count
    - Suitable for: Any scale (delegated to DataSource)

    Usage:
        ```python
        # With SQL DataSource (business layer)
        from your_app import SQLSkillQualityDataSource
        from myrm_agent_harness import UniversalAggregator

        sql_source = SQLSkillQualityDataSource(session_factory)
        aggregator = UniversalAggregator(sql_source)
        metrics = await aggregator.get_global_metrics()

        # With custom DataSource (any backend)
        class MyDataSource:
            async def query_raw_records(self, skill_id=None, time_range_days=30, filters=None):
                ...
            async def query_aggregated(self, group_by, time_range_days=30, filters=None):
                return []

        custom_source = MyDataSource()
        aggregator = UniversalAggregator(custom_source)
        comparison = await aggregator.compare(before_range_days=14, after_range_days=7)
        ```
    """

    def __init__(self, data_source: SkillQualityDataSource):
        """Initialize universal aggregator

        Args:
            data_source: SkillQualityDataSource implementation (SQL/Redis/File/API)
        """
        self._data_source = data_source

    async def aggregate_by_skill(
        self, skill_id: str | None = None, time_range_days: int = 30
    ) -> list[SkillQualityAggregate]:
        """Aggregate quality metrics by skill

        Strategy:
        1. Try pre-aggregated data from DataSource (fast path)
        2. Fall back to raw records aggregation (universal path)

        Args:
            skill_id: Optional skill filter
            time_range_days: Time window for aggregation

        Returns:
            List of SkillQualityAggregate sorted by quality score descending
        """
        cutoff_date = datetime.now() - timedelta(days=time_range_days)

        try:
            pre_agg = await self._data_source.query_aggregated(
                group_by="skill_id",
                time_range_days=time_range_days,
                filters={"skill_id": skill_id} if skill_id else None,
            )

            if pre_agg:
                logger.debug(f"Using pre-aggregated data: {len(pre_agg)} groups")
                return self._build_skill_aggregates_from_preag(pre_agg, cutoff_date)
        except Exception as e:
            logger.warning(f"Pre-aggregation failed, falling back to raw records: {e}")

        logger.debug("Using raw records aggregation")
        records = await self._data_source.query_raw_records(skill_id=skill_id, time_range_days=time_range_days)

        return self._aggregate_records_by_skill(records, cutoff_date)

    async def aggregate_by_user(self, time_range_days: int = 30) -> list[UserQualityAggregate]:
        """Aggregate quality metrics by user.

        In single-user sandbox mode, returns a single aggregate for the current user.

        Args:
            time_range_days: Time window for aggregation

        Returns:
            List of UserQualityAggregate sorted by quality score descending
        """
        cutoff_date = datetime.now() - timedelta(days=time_range_days)

        try:
            pre_agg = await self._data_source.query_aggregated(
                group_by="user_id",
                time_range_days=time_range_days,
            )

            if pre_agg:
                logger.debug(f"Using pre-aggregated data: {len(pre_agg)} groups")
                return self._build_user_aggregates_from_preagg(pre_agg, cutoff_date)
        except Exception as e:
            logger.warning(f"Pre-aggregation failed, falling back to raw records: {e}")

        logger.debug("Using raw records aggregation")
        records = await self._data_source.query_raw_records(
            skill_id=None,
            time_range_days=time_range_days,
        )

        return self._aggregate_records_by_user(records, cutoff_date)

    async def aggregate_by_dimension(
        self, dimension: AggregateDimension, time_range_days: int = 30
    ) -> dict[str, SkillQualityAggregate]:
        """Aggregate quality metrics by dimension

        Delegates to aggregate_by_skill/aggregate_by_user based on dimension.

        Args:
            dimension: Aggregation dimension
            time_range_days: Time window for aggregation

        Returns:
            Dictionary mapping dimension value to aggregate
        """
        if dimension == AggregateDimension.SKILL:
            aggregates = await self.aggregate_by_skill(time_range_days=time_range_days)
            return {agg.skill_id: agg for agg in aggregates}
        elif dimension == AggregateDimension.USER:
            user_aggregates = await self.aggregate_by_user(time_range_days=time_range_days)
            return {agg.user_id or "default": agg for agg in user_aggregates}
        else:
            return {}

    async def get_global_metrics(self, time_range_days: int = 30) -> GlobalQualityMetrics:
        """Get global quality metrics across all skills/users

        Args:
            time_range_days: Time window for aggregation

        Returns:
            GlobalQualityMetrics with system-wide statistics
        """
        records = await self._data_source.query_raw_records(skill_id=None, time_range_days=time_range_days)

        if not records:
            return GlobalQualityMetrics(
                total_skills=0,
                total_users=0,
                total_executions=0,
                avg_quality_score=0.0,
                median_quality_score=0.0,
                quality_std=0.0,
                top_skills_count=0,
                bottom_skills_count=0,
                optimization_rate=0.0,
                calculated_at=datetime.now(),
            )

        all_scores = [r.overall_score for r in records]
        unique_skills = len(set(r.skill_id for r in records))
        unique_users = 1

        sorted_scores = sorted(all_scores)
        median_score = sorted_scores[len(sorted_scores) // 2]

        top_skills_count = sum(1 for s in all_scores if s >= 0.8)
        bottom_skills_count = sum(1 for s in all_scores if s < 0.5)

        return GlobalQualityMetrics(
            total_skills=unique_skills,
            total_users=unique_users,
            total_executions=len(records),
            avg_quality_score=sum(all_scores) / len(all_scores),
            median_quality_score=median_score,
            quality_std=sample_std(all_scores),
            top_skills_count=top_skills_count,
            bottom_skills_count=bottom_skills_count,
            optimization_rate=0.0,
            calculated_at=datetime.now(),
        )

    async def compare(
        self, before_range_days: int, after_range_days: int, skill_id: str | None = None
    ) -> list[ComparisonResult]:
        """Compare quality metrics across two time periods

        Time windows are non-overlapping:
        - before: [now - before_range_days, now - after_range_days]
        - after:  [now - after_range_days, now]

        Args:
            before_range_days: Days ago for "before" window start
            after_range_days: Days ago for "after" window start (0 = now)
            skill_id: Optional skill filter

        Returns:
            List of ComparisonResult showing before/after delta
        """
        now = datetime.now()
        before_start = now - timedelta(days=before_range_days)
        before_end = now - timedelta(days=after_range_days)
        after_start = before_end

        before_records = await self._data_source.query_raw_records(skill_id=skill_id, time_range_days=before_range_days)
        after_records = await self._data_source.query_raw_records(skill_id=skill_id, time_range_days=after_range_days)

        before_filtered = [r for r in before_records if r.recorded_at < before_end]

        before_by_skill = self._aggregate_records_by_skill(before_filtered, before_start)
        after_by_skill = self._aggregate_records_by_skill(after_records, after_start)

        before_map = {r.skill_id: r for r in before_by_skill}
        after_map = {r.skill_id: r for r in after_by_skill}

        results: list[ComparisonResult] = []
        all_skill_ids = set(before_map.keys()) | set(after_map.keys())

        for sid in all_skill_ids:
            before_agg = before_map.get(sid)
            after_agg = after_map.get(sid)

            if not before_agg or not after_agg:
                continue

            delta_quality = after_agg.avg_quality_score - before_agg.avg_quality_score
            delta_success_rate = after_agg.avg_success_rate - before_agg.avg_success_rate
            delta_token_efficiency = after_agg.avg_token_efficiency - before_agg.avg_token_efficiency
            delta_execution_time = after_agg.avg_execution_time - before_agg.avg_execution_time
            delta_user_satisfaction = after_agg.avg_user_satisfaction - before_agg.avg_user_satisfaction
            improvement_pct = (
                (delta_quality / before_agg.avg_quality_score * 100) if before_agg.avg_quality_score > 0 else 0.0
            )

            results.append(
                ComparisonResult(
                    before=before_agg,
                    after=after_agg,
                    delta_quality=delta_quality,
                    delta_success_rate=delta_success_rate,
                    delta_token_efficiency=delta_token_efficiency,
                    delta_execution_time=delta_execution_time,
                    delta_user_satisfaction=delta_user_satisfaction,
                    improvement_pct=improvement_pct,
                    is_statistically_significant=False,
                    p_value=None,
                    compared_at=datetime.now(),
                )
            )

        results.sort(key=lambda x: abs(x.delta_quality), reverse=True)
        return results

    async def get_quality_percentiles(self, skill_id: str | None = None, time_range_days: int = 30) -> dict[str, float]:
        """Get quality score percentiles

        Args:
            skill_id: Optional skill filter
            time_range_days: Time window for aggregation

        Returns:
            Dictionary with percentile values (p50, p90, p95, p99)
        """
        records = await self._data_source.query_raw_records(skill_id=skill_id, time_range_days=time_range_days)

        if not records:
            return {"p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0}

        scores = sorted([r.overall_score for r in records])

        return {
            "p50": calc_percentile(scores, 50),
            "p90": calc_percentile(scores, 90),
            "p95": calc_percentile(scores, 95),
            "p99": calc_percentile(scores, 99),
        }

    def _aggregate_records_by_skill(
        self, records: list[SkillQualitySnapshot], cutoff_date: datetime
    ) -> list[SkillQualityAggregate]:
        """Aggregate raw records by skill (universal path)

        Args:
            records: Raw quality snapshots
            cutoff_date: Time range start

        Returns:
            List of SkillQualityAggregate
        """
        skill_groups: dict[str, list[SkillQualitySnapshot]] = defaultdict(list)

        for record in records:
            skill_groups[record.skill_id].append(record)

        results: list[SkillQualityAggregate] = []
        for skill_id, group_records in skill_groups.items():
            if not group_records:
                continue

            overall_scores = [r.overall_score for r in group_records]
            success_rates = [r.success_rate for r in group_records]
            token_effs = [r.token_efficiency for r in group_records]
            exec_times = [r.execution_time for r in group_records]
            satisfactions = [r.user_satisfaction for r in group_records]

            unique_users = 1

            results.append(
                SkillQualityAggregate(
                    skill_id=skill_id,
                    sample_count=len(group_records),
                    avg_quality_score=sum(overall_scores) / len(overall_scores),
                    quality_std=sample_std(overall_scores),
                    avg_success_rate=sum(success_rates) / len(success_rates),
                    avg_token_efficiency=sum(token_effs) / len(token_effs),
                    avg_execution_time=sum(exec_times) / len(exec_times),
                    avg_user_satisfaction=sum(satisfactions) / len(satisfactions),
                    total_executions=len(group_records),
                    user_count=unique_users,
                    optimization_count=0,
                    last_optimization=None,
                    time_range_start=cutoff_date,
                    time_range_end=datetime.now(),
                )
            )

        results.sort(key=lambda x: x.avg_quality_score, reverse=True)
        return results

    def _aggregate_records_by_user(
        self, records: list[SkillQualitySnapshot], cutoff_date: datetime
    ) -> list[UserQualityAggregate]:
        """Aggregate raw records by user (universal path)

        Args:
            records: Raw quality snapshots
            cutoff_date: Time range start

        Returns:
            List of UserQualityAggregate
        """
        if not records:
            return []

        overall_scores = [r.overall_score for r in records]
        unique_skills = len(set(r.skill_id for r in records))

        results: list[UserQualityAggregate] = [
            UserQualityAggregate(
                user_id="default",
                sample_count=len(records),
                avg_quality_score=sum(overall_scores) / len(overall_scores),
                unique_skills_used=unique_skills,
                total_executions=len(records),
                favorite_skill=None,
                time_range_start=cutoff_date,
                time_range_end=datetime.now(),
            )
        ]

        results.sort(key=lambda x: x.avg_quality_score, reverse=True)
        return results

    def _build_skill_aggregates_from_preag(
        self, pre_agg: list[dict[str, float]], cutoff_date: datetime
    ) -> list[SkillQualityAggregate]:
        """Build SkillQualityAggregate from pre-aggregated data (fast path)

        Args:
            pre_agg: Pre-aggregated data from DataSource
            cutoff_date: Time range start

        Returns:
            List of SkillQualityAggregate
        """
        results: list[SkillQualityAggregate] = []

        for item in pre_agg:
            results.append(
                SkillQualityAggregate(
                    skill_id=item.get("skill_id", ""),
                    sample_count=int(item.get("sample_count", 0)),
                    avg_quality_score=float(item.get("avg_quality_score", 0.0)),
                    quality_std=float(item.get("quality_std", 0.0)),
                    avg_success_rate=float(item.get("avg_success_rate", 0.0)),
                    avg_token_efficiency=float(item.get("avg_token_efficiency", 0.0)),
                    avg_execution_time=float(item.get("avg_execution_time", 0.0)),
                    avg_user_satisfaction=float(item.get("avg_user_satisfaction", 0.0)),
                    total_executions=int(item.get("total_executions", 0)),
                    user_count=int(item.get("user_count", 0)),
                    optimization_count=int(item.get("optimization_count", 0)),
                    last_optimization=None,
                    time_range_start=cutoff_date,
                    time_range_end=datetime.now(),
                )
            )

        results.sort(key=lambda x: x.avg_quality_score, reverse=True)
        return results

    def _build_user_aggregates_from_preagg(
        self, pre_agg: list[dict[str, float]], cutoff_date: datetime
    ) -> list[UserQualityAggregate]:
        """Build UserQualityAggregate from pre-aggregated data (fast path)

        Args:
            pre_agg: Pre-aggregated data from DataSource
            cutoff_date: Time range start

        Returns:
            List of UserQualityAggregate
        """
        results: list[UserQualityAggregate] = []

        for item in pre_agg:
            results.append(
                UserQualityAggregate(
                    user_id=item.get(""),
                    sample_count=int(item.get("sample_count", 0)),
                    avg_quality_score=float(item.get("avg_quality_score", 0.0)),
                    unique_skills_used=int(item.get("unique_skills_used", 0)),
                    total_executions=int(item.get("total_executions", 0)),
                    favorite_skill=None,
                    time_range_start=cutoff_date,
                    time_range_end=datetime.now(),
                )
            )

        results.sort(key=lambda x: x.avg_quality_score, reverse=True)
        return results
