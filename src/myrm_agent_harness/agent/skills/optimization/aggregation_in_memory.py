"""In-Memory Skill Quality Aggregator

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- .protocols.SkillQualityAggregator (POS: 聚合Protocol)
- .protocols.SkillOptimizationStorage (POS: 存储Protocol)
- .types.* (POS: 聚合数据类型)

[OUTPUT]
- InMemoryAggregator: 内存聚合实现

[POS]
In-memory aggregation implementation. Framework-provided, ready-to-use for local/tauri/dev scenarios.

"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .math_utils import percentile as calc_percentile
from .math_utils import sample_std
from .protocols import SkillOptimizationStorage, SkillQualityAggregator
from .types import (
    AggregateDimension,
    ComparisonResult,
    GlobalQualityMetrics,
    SkillQualityAggregate,
    UserQualityAggregate,
)

if TYPE_CHECKING:
    from .types import SkillQualityScore


class InMemoryAggregator(SkillQualityAggregator):
    """In-Memory Skill Quality Aggregator

    Framework-level out-of-the-box aggregator implementation.
    Reads from SkillOptimizationStorage and computes aggregates in memory.

    Features:
    - Zero configuration required
    - Works with any SkillOptimizationStorage implementation
    - Suitable for local/tauri/dev scenarios
    - Full aggregation capability without external dependencies

    Performance:
    - Time: O(N) where N is quality snapshots count
    - Space: O(N) for intermediate data structures
    - Suitable for: < 100K snapshots

    Usage:
        ```python
        from myrm_agent_harness.agent.skills.optimization import (
            InMemoryStorage,
            InMemoryAggregator)

        storage = InMemoryStorage()
        aggregator = InMemoryAggregator(storage)

        metrics = await aggregator.get_global_metrics()
        by_skill = await aggregator.aggregate_by_skill()
        ```
    """

    def __init__(self, storage: SkillOptimizationStorage):
        """Initialize aggregator

        Args:
            storage: SkillOptimizationStorage implementation (InMemory, SQLAlchemy, etc.)
        """
        self._storage = storage

    async def aggregate_by_skill(
        self, skill_id: str | None = None, time_range_days: int = 30
    ) -> list[SkillQualityAggregate]:
        """Aggregate quality metrics by skill"""
        cutoff_date = datetime.now() - timedelta(days=time_range_days)
        aggregates: dict[str, list[SkillQualityScore]] = {}

        if skill_id:
            snapshots = await self._storage.get_quality_history(skill_id, days=time_range_days)
            aggregates[skill_id] = [score for _, score in snapshots]
        else:
            top_skills = await self._storage.get_top_skills(limit=1000)
            bottom_skills = await self._storage.get_bottom_skills(limit=1000)
            all_skill_ids = list(set([sid for sid, _ in top_skills + bottom_skills]))

            for sid in all_skill_ids:
                snapshots = await self._storage.get_quality_history(sid, days=time_range_days)
                if snapshots:
                    aggregates[sid] = [score for _, score in snapshots]

        results: list[SkillQualityAggregate] = []
        for sid, scores in aggregates.items():
            if not scores:
                continue

            overall_scores = [s.overall_score for s in scores]
            success_rates = [s.success_rate for s in scores]
            token_effs = [s.token_efficiency for s in scores]
            exec_times = [s.execution_time for s in scores]
            satisfactions = [s.user_satisfaction for s in scores]

            results.append(
                SkillQualityAggregate(
                    skill_id=sid,
                    sample_count=len(scores),
                    avg_quality_score=sum(overall_scores) / len(overall_scores),
                    quality_std=sample_std(overall_scores),
                    avg_success_rate=sum(success_rates) / len(success_rates),
                    avg_token_efficiency=sum(token_effs) / len(token_effs),
                    avg_execution_time=sum(exec_times) / len(exec_times),
                    avg_user_satisfaction=sum(satisfactions) / len(satisfactions),
                    total_executions=len(scores),
                    user_count=1,
                    optimization_count=0,
                    last_optimization=None,
                    time_range_start=cutoff_date,
                    time_range_end=datetime.now(),
                )
            )

        results.sort(key=lambda x: x.avg_quality_score, reverse=True)
        return results

    async def aggregate_by_user(self, time_range_days: int = 30) -> list[UserQualityAggregate]:
        """Aggregate quality metrics by user

        Note: Current storage protocol doesn't support per-user metrics directly.
        Returns empty list as placeholder.
        """
        return []

    async def aggregate_by_dimension(
        self, dimension: AggregateDimension, time_range_days: int = 30
    ) -> dict[str, SkillQualityAggregate]:
        """Aggregate quality metrics by custom dimension

        Note: Current implementation supports basic dimensions.
        Extended dimensions (user_tier, region, etc.) require additional metadata.
        """
        if dimension == AggregateDimension.SKILL:
            aggregates = await self.aggregate_by_skill(time_range_days=time_range_days)
            return {agg.skill_id: agg for agg in aggregates}
        elif dimension == AggregateDimension.USER:
            aggregates = await self.aggregate_by_user(time_range_days=time_range_days)
            return {agg.user_id: agg for agg in aggregates}
        else:
            return {}

    async def get_global_metrics(self, time_range_days: int = 30) -> GlobalQualityMetrics:
        """Get global quality metrics across all skills/users"""
        aggregates = await self.aggregate_by_skill(time_range_days=time_range_days)

        if not aggregates:
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

        all_scores = [agg.avg_quality_score for agg in aggregates]
        sorted_scores = sorted(all_scores)

        median = sorted_scores[len(sorted_scores) // 2] if sorted_scores else 0.0

        top_skills_count = len([s for s in all_scores if s >= 0.8])
        bottom_skills_count = len([s for s in all_scores if s < 0.5])

        total_executions = sum(agg.total_executions for agg in aggregates)
        total_optimizations = sum(agg.optimization_count for agg in aggregates)

        optimization_rate = total_optimizations / total_executions if total_executions > 0 else 0.0

        return GlobalQualityMetrics(
            total_skills=len(aggregates),
            total_users=0,
            total_executions=total_executions,
            avg_quality_score=sum(all_scores) / len(all_scores),
            median_quality_score=median,
            quality_std=sample_std(all_scores),
            top_skills_count=top_skills_count,
            bottom_skills_count=bottom_skills_count,
            optimization_rate=optimization_rate,
            calculated_at=datetime.now(),
        )

    async def compare(
        self, before_range_days: int, after_range_days: int, skill_id: str | None = None
    ) -> list[ComparisonResult]:
        """Compare quality metrics across two time periods"""
        before_start = datetime.now() - timedelta(days=before_range_days)
        before_end = datetime.now() - timedelta(days=after_range_days)
        after_start = before_end
        after_end = datetime.now()

        if skill_id:
            skill_ids = [skill_id]
        else:
            all_aggregates = await self.aggregate_by_skill(time_range_days=before_range_days)
            skill_ids = [agg.skill_id for agg in all_aggregates]

        results: list[ComparisonResult] = []

        for sid in skill_ids:
            before_snapshots = await self._storage.get_quality_history(sid, days=before_range_days)
            after_snapshots = await self._storage.get_quality_history(sid, days=after_range_days)

            if not before_snapshots or not after_snapshots:
                continue

            before_scores = [score for _, score in before_snapshots]
            after_scores = [score for _, score in after_snapshots]

            before_avg = sum(s.overall_score for s in before_scores) / len(before_scores)
            after_avg = sum(s.overall_score for s in after_scores) / len(after_scores)

            delta_quality = after_avg - before_avg

            before_sr = sum(s.success_rate for s in before_scores) / len(before_scores)
            after_sr = sum(s.success_rate for s in after_scores) / len(after_scores)
            delta_sr = after_sr - before_sr

            before_te = sum(s.token_efficiency for s in before_scores) / len(before_scores)
            after_te = sum(s.token_efficiency for s in after_scores) / len(after_scores)
            delta_te = after_te - before_te

            improvement_pct = (delta_quality / before_avg * 100) if before_avg > 0 else 0.0

            before_exec_time = sum(s.execution_time for s in before_scores) / len(before_scores)
            after_exec_time = sum(s.execution_time for s in after_scores) / len(after_scores)
            delta_exec_time = after_exec_time - before_exec_time

            before_satisfaction = sum(s.user_satisfaction for s in before_scores) / len(before_scores)
            after_satisfaction = sum(s.user_satisfaction for s in after_scores) / len(after_scores)
            delta_satisfaction = after_satisfaction - before_satisfaction

            before_agg = SkillQualityAggregate(
                skill_id=sid,
                sample_count=len(before_scores),
                avg_quality_score=before_avg,
                quality_std=sample_std([s.overall_score for s in before_scores]),
                avg_success_rate=before_sr,
                avg_token_efficiency=before_te,
                avg_execution_time=before_exec_time,
                avg_user_satisfaction=before_satisfaction,
                total_executions=len(before_scores),
                user_count=1,
                optimization_count=0,
                time_range_start=before_start,
                time_range_end=before_end,
            )

            after_agg = SkillQualityAggregate(
                skill_id=sid,
                sample_count=len(after_scores),
                avg_quality_score=after_avg,
                quality_std=sample_std([s.overall_score for s in after_scores]),
                avg_success_rate=after_sr,
                avg_token_efficiency=after_te,
                avg_execution_time=after_exec_time,
                avg_user_satisfaction=after_satisfaction,
                total_executions=len(after_scores),
                user_count=1,
                optimization_count=0,
                time_range_start=after_start,
                time_range_end=after_end,
            )

            is_significant = False
            p_value = None
            if len(before_scores) >= 10 and len(after_scores) >= 10:
                try:
                    from scipy import stats

                    before_std = before_agg.quality_std
                    after_std = after_agg.quality_std
                    _, p_value = stats.ttest_ind_from_stats(
                        before_avg, before_std, len(before_scores), after_avg, after_std, len(after_scores)
                    )
                    is_significant = p_value < 0.05
                except Exception:
                    pass

            results.append(
                ComparisonResult(
                    before=before_agg,
                    after=after_agg,
                    delta_quality=delta_quality,
                    delta_success_rate=delta_sr,
                    delta_token_efficiency=delta_te,
                    delta_execution_time=delta_exec_time,
                    delta_user_satisfaction=delta_satisfaction,
                    improvement_pct=improvement_pct,
                    is_statistically_significant=is_significant,
                    p_value=p_value,
                    compared_at=datetime.now(),
                )
            )

        results.sort(key=lambda x: x.improvement_pct, reverse=True)
        return results

    async def get_quality_percentiles(self, skill_id: str | None = None, time_range_days: int = 30) -> dict[str, float]:
        """Get quality score percentiles (P50/P90/P95/P99)"""
        aggregates = await self.aggregate_by_skill(skill_id=skill_id, time_range_days=time_range_days)

        if not aggregates:
            return {"p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0}

        all_scores = sorted([agg.avg_quality_score for agg in aggregates])

        return {
            "p50": calc_percentile(all_scores, 50),
            "p90": calc_percentile(all_scores, 90),
            "p95": calc_percentile(all_scores, 95),
            "p99": calc_percentile(all_scores, 99),
        }
