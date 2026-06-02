"""Streaming Skill Quality Aggregator

Processes raw skill quality events into aggregated metrics incrementally.
Supports both in-memory buffering and persistent storage synchronization.

[INPUT]
- (none)

[OUTPUT]
- StreamingAggregator: Streaming Skill Quality Aggregator

[POS]
Streaming Skill Quality Aggregator
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from .event_emitter import EventEmitter
from .math_utils import percentile as calc_percentile
from .math_utils import sample_std
from .protocols import SkillOptimizationStorage, SkillQualityAggregator
from .types import (
    AggregateDimension,
    ComparisonResult,
    GlobalQualityMetrics,
    SkillQualityAggregate,
    SkillQualityScore,
    UserQualityAggregate,
)

logger = logging.getLogger(__name__)


class StreamingAggregator(SkillQualityAggregator):
    """Streaming Skill Quality Aggregator

    Real-time incremental aggregation based on event stream.
    Automatically updates statistics when skill_executed or quality_updated events fire.

    Features:
    - O(1) query time vs O(N) for full scan
    - Real-time updates via EventEmitter subscription
    - Sliding window support (1h, 24h, 7d)
    - Memory-efficient for high-frequency queries

    Performance:
    - Query: O(1) time, no full data scan required
    - Update: O(1) time per event
    - Space: O(S * W) where S=skills, W=window buckets

    Suitable for:
    - Production dashboards with real-time updates
    - High-frequency queries (< 10ms response)
    - Live monitoring systems

    Usage:
        ```python
        from myrm_agent_harness.agent.skills.optimization import (
            InMemoryStorage,
            EventEmitter,
            StreamingAggregator)

        storage = InMemoryStorage()
        emitter = EventEmitter()
        aggregator = StreamingAggregator(storage, emitter)

        # Aggregator auto-updates on events
        await emitter.emit("skill_executed", {
            "skill_id": "pdf-generator",
            "quality_score": score,
        })

        # Instant query (no full scan)
        metrics = await aggregator.get_global_metrics()
        ```
    """

    def __init__(
        self,
        storage: SkillOptimizationStorage,
        event_emitter: EventEmitter,
        enable_snapshot: bool = True,
        snapshot_interval_seconds: int = 300,
    ):
        """Initialize streaming aggregator

        Args:
            storage: SkillOptimizationStorage for fallback queries and snapshot persistence
            event_emitter: EventEmitter for real-time event subscriptions
            enable_snapshot: Enable periodic snapshot persistence (default: True)
            snapshot_interval_seconds: Snapshot interval in seconds (default: 300 = 5min)
        """
        self._storage = storage
        self._emitter = event_emitter
        self._enable_snapshot = enable_snapshot
        self._snapshot_interval = snapshot_interval_seconds

        self._skill_stats: dict[str, _SkillStats] = defaultdict(_SkillStats)
        self._global_stats = _GlobalStats()
        self._last_update = datetime.now()
        self._last_snapshot = datetime.now()

        self._emitter.on("skill_executed", self._on_skill_executed)
        self._emitter.on("quality_updated", self._on_quality_updated)

        if self._enable_snapshot:
            import asyncio

            self._bg_tasks: set[asyncio.Task[None]] = set()
            for coro in (self._load_snapshot(), self._auto_save_snapshots()):
                snapshot_task = asyncio.create_task(coro)
                self._bg_tasks.add(snapshot_task)
                snapshot_task.add_done_callback(self._bg_tasks.discard)

    async def aggregate_by_skill(
        self, skill_id: str | None = None, time_range_days: int = 30
    ) -> list[SkillQualityAggregate]:
        """Aggregate quality metrics by skill"""
        cutoff = datetime.now() - timedelta(days=time_range_days)

        results: list[SkillQualityAggregate] = []

        if skill_id:
            stats = self._skill_stats.get(skill_id)
            if stats:
                agg = stats.to_aggregate(skill_id, cutoff, datetime.now())
                if agg.sample_count > 0:
                    results.append(agg)
        else:
            for sid, stats in self._skill_stats.items():
                agg = stats.to_aggregate(sid, cutoff, datetime.now())
                if agg.sample_count > 0:
                    results.append(agg)

        results.sort(key=lambda x: x.avg_quality_score, reverse=True)
        return results

    async def aggregate_by_user(self, time_range_days: int = 30) -> list[UserQualityAggregate]:
        """Aggregate quality metrics by user

        Note: User-level aggregation requires additional metadata.
        This is a placeholder for future enhancement.
        """
        return []

    async def aggregate_by_dimension(
        self, dimension: AggregateDimension, time_range_days: int = 30
    ) -> dict[str, SkillQualityAggregate]:
        """Aggregate quality metrics by custom dimension"""
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
        """Compare quality metrics across two time periods

        Note: Streaming aggregator tracks current window only.
        For historical comparisons, falls back to storage layer.
        """
        results: list[ComparisonResult] = []

        if skill_id:
            skill_ids = [skill_id]
        else:
            skill_ids = list(self._skill_stats.keys())

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

            before_agg = SkillQualityAggregate(
                skill_id=sid,
                sample_count=len(before_scores),
                avg_quality_score=before_avg,
                quality_std=sample_std([s.overall_score for s in before_scores]),
                avg_success_rate=before_sr,
                avg_token_efficiency=before_te,
                avg_execution_time=sum(s.execution_time for s in before_scores) / len(before_scores),
                avg_user_satisfaction=sum(s.user_satisfaction for s in before_scores) / len(before_scores),
                total_executions=len(before_scores),
                user_count=1,
                optimization_count=0,
                time_range_start=datetime.now() - timedelta(days=before_range_days),
                time_range_end=datetime.now() - timedelta(days=after_range_days),
            )

            after_agg = SkillQualityAggregate(
                skill_id=sid,
                sample_count=len(after_scores),
                avg_quality_score=after_avg,
                quality_std=sample_std([s.overall_score for s in after_scores]),
                avg_success_rate=after_sr,
                avg_token_efficiency=after_te,
                avg_execution_time=sum(s.execution_time for s in after_scores) / len(after_scores),
                avg_user_satisfaction=sum(s.user_satisfaction for s in after_scores) / len(after_scores),
                total_executions=len(after_scores),
                user_count=1,
                optimization_count=0,
                time_range_start=datetime.now() - timedelta(days=after_range_days),
                time_range_end=datetime.now(),
            )

            before_exec_time = sum(s.execution_time for s in before_scores) / len(before_scores)
            after_exec_time = sum(s.execution_time for s in after_scores) / len(after_scores)
            delta_exec_time = after_exec_time - before_exec_time

            before_satisfaction = sum(s.user_satisfaction for s in before_scores) / len(before_scores)
            after_satisfaction = sum(s.user_satisfaction for s in after_scores) / len(after_scores)
            delta_satisfaction = after_satisfaction - before_satisfaction

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
                    is_statistically_significant=False,
                    p_value=None,
                    compared_at=datetime.now(),
                )
            )

        results.sort(key=lambda x: x.improvement_pct, reverse=True)
        return results

    async def _on_skill_executed(self, event: str, payload: dict) -> None:
        """Event handler: skill executed"""
        skill_id = payload.get("skill_id")
        quality_score: SkillQualityScore | None = payload.get("quality_score")

        if not skill_id or not quality_score:
            return

        stats = self._skill_stats[skill_id]
        stats.update(quality_score)

        self._global_stats.total_executions += 1
        self._last_update = datetime.now()

    async def _on_quality_updated(self, event: str, payload: dict) -> None:
        """Event handler: quality score updated"""
        skill_id = payload.get("skill_id")
        quality_score: SkillQualityScore | None = payload.get("quality_score")

        if not skill_id or not quality_score:
            return

        stats = self._skill_stats[skill_id]
        stats.update(quality_score)

        self._last_update = datetime.now()

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

    async def save_snapshot(self) -> None:
        """Persist current aggregation state to storage

        Saves the current in-memory statistics to storage for fast recovery after restart.
        Snapshot includes all skill stats and global stats.

        Performance:
        - Write time: O(S) where S is number of skills
        - Typically <100ms for 100 skills

        Usage:
            ```python
            # Manual snapshot
            await aggregator.save_snapshot()

            # Auto-snapshot (default, every 5min)
            aggregator = StreamingAggregator(storage, emitter, enable_snapshot=True)
            ```
        """
        if not self._enable_snapshot:
            return

        try:
            snapshot_data = {
                "timestamp": self._last_update.isoformat(),
                "skill_count": len(self._skill_stats),
                "total_executions": self._global_stats.total_executions,
                "skills": {
                    skill_id: {
                        "count": stats.count,
                        "sum_quality": stats.sum_quality,
                        "sum_quality_sq": stats.sum_quality_sq,
                        "sum_success_rate": stats.sum_success_rate,
                        "sum_token_eff": stats.sum_token_eff,
                        "sum_exec_time": stats.sum_exec_time,
                        "sum_satisfaction": stats.sum_satisfaction,
                    }
                    for skill_id, stats in self._skill_stats.items()
                },
            }

            import json

            from .types import (
                OptimizationResult,
                OptimizationStatus,
                SecurityValidationResult,
                SkillQualityScore,
                SkillType,
            )

            await self._storage.save_optimization_record(
                OptimizationResult(
                    skill_id="__streaming_aggregator_snapshot__",
                    skill_type=SkillType.USER,
                    baseline_score=SkillQualityScore(
                        success_rate=0.0,
                        token_efficiency=0.0,
                        execution_time=0.0,
                        user_satisfaction=0.0,
                        call_frequency=0.0,
                    ),
                    optimized_content=json.dumps(snapshot_data),
                    security_validation=SecurityValidationResult(passed=True, issues=[]),
                    status=OptimizationStatus.COMPLETED,
                    started_at=self._last_update,
                    completed_at=self._last_update,
                )
            )

            self._last_snapshot = datetime.now()
            logger.info(
                f"Snapshot saved: {len(self._skill_stats)} skills, {self._global_stats.total_executions} executions"
            )

        except Exception as e:
            logger.error(f"Failed to save snapshot: {e}")

    async def _load_snapshot(self) -> None:
        """Restore aggregation state from last snapshot

        Loads the last saved snapshot to quickly restore in-memory statistics after restart.
        Falls back gracefully if no snapshot exists.

        Performance:
        - Read time: O(S) where S is number of skills
        - Typically <50ms for 100 skills
        """
        try:
            import json

            record = await self._storage.get_optimization_record("__streaming_aggregator_snapshot__")

            if not record or not record.optimized_content:
                logger.info("No snapshot found, starting fresh")
                return

            snapshot = json.loads(record.optimized_content)

            for skill_id, stats_data in snapshot.get("skills", {}).items():
                stats = _SkillStats()
                stats.count = stats_data["count"]
                stats.sum_quality = stats_data["sum_quality"]
                stats.sum_quality_sq = stats_data["sum_quality_sq"]
                stats.sum_success_rate = stats_data["sum_success_rate"]
                stats.sum_token_eff = stats_data["sum_token_eff"]
                stats.sum_exec_time = stats_data["sum_exec_time"]
                stats.sum_satisfaction = stats_data["sum_satisfaction"]
                self._skill_stats[skill_id] = stats

            self._global_stats.total_executions = snapshot.get("total_executions", 0)
            logger.info(
                f"Snapshot loaded: {len(self._skill_stats)} skills, {self._global_stats.total_executions} executions"
            )

        except Exception as e:
            logger.warning(f"Failed to load snapshot: {e}, starting fresh")

    async def _auto_save_snapshots(self) -> None:
        """Auto-save snapshots periodically"""
        import asyncio

        while True:
            await asyncio.sleep(self._snapshot_interval)
            await self.save_snapshot()


class _SkillStats:
    """Internal: Per-skill running statistics with sliding window"""

    def __init__(self):
        self.count = 0
        self.sum_quality = 0.0
        self.sum_quality_sq = 0.0
        self.sum_success_rate = 0.0
        self.sum_token_eff = 0.0
        self.sum_exec_time = 0.0
        self.sum_satisfaction = 0.0

        self.window_1h: list[tuple[datetime, SkillQualityScore]] = []
        self.window_24h: list[tuple[datetime, SkillQualityScore]] = []
        self.window_7d: list[tuple[datetime, SkillQualityScore]] = []

    def update(self, score: SkillQualityScore) -> None:
        """Update running statistics with new score"""
        now = datetime.now()
        overall = score.overall_score
        self.count += 1
        self.sum_quality += overall
        self.sum_quality_sq += overall * overall
        self.sum_success_rate += score.success_rate
        self.sum_token_eff += score.token_efficiency
        self.sum_exec_time += score.execution_time
        self.sum_satisfaction += score.user_satisfaction

        self.window_1h.append((now, score))
        self.window_24h.append((now, score))
        self.window_7d.append((now, score))

        self._cleanup_windows(now)

    def _cleanup_windows(self, now: datetime) -> None:
        """Remove expired entries from sliding windows"""
        cutoff_1h = now - timedelta(hours=1)
        cutoff_24h = now - timedelta(hours=24)
        cutoff_7d = now - timedelta(days=7)

        self.window_1h = [(ts, s) for ts, s in self.window_1h if ts >= cutoff_1h]
        self.window_24h = [(ts, s) for ts, s in self.window_24h if ts >= cutoff_24h]
        self.window_7d = [(ts, s) for ts, s in self.window_7d if ts >= cutoff_7d]

    def get_window_stats(self, window: str) -> tuple[int, float, float]:
        """Get statistics for specific window

        Returns:
            (count, avg_quality, std_quality)
        """
        if window == "1h":
            scores = self.window_1h
        elif window == "24h":
            scores = self.window_24h
        elif window == "7d":
            scores = self.window_7d
        else:
            return 0, 0.0, 0.0

        if not scores:
            return 0, 0.0, 0.0

        qualities = [s.overall_score for _, s in scores]
        avg = sum(qualities) / len(qualities)

        return len(scores), avg, sample_std(qualities)

    def to_aggregate(self, skill_id: str, start: datetime, end: datetime) -> SkillQualityAggregate:
        """Convert to SkillQualityAggregate"""
        if self.count == 0:
            return SkillQualityAggregate(
                skill_id=skill_id,
                sample_count=0,
                avg_quality_score=0.0,
                quality_std=0.0,
                avg_success_rate=0.0,
                avg_token_efficiency=0.0,
                avg_execution_time=0.0,
                avg_user_satisfaction=0.0,
                total_executions=0,
                user_count=0,
                optimization_count=0,
                time_range_start=start,
                time_range_end=end,
            )

        avg_quality = self.sum_quality / self.count
        if self.count < 2:
            std = 0.0
        else:
            variance = (self.sum_quality_sq - self.count * avg_quality * avg_quality) / (self.count - 1)
            std = variance**0.5 if variance > 0 else 0.0

        return SkillQualityAggregate(
            skill_id=skill_id,
            sample_count=self.count,
            avg_quality_score=avg_quality,
            quality_std=std,
            avg_success_rate=self.sum_success_rate / self.count,
            avg_token_efficiency=self.sum_token_eff / self.count,
            avg_execution_time=self.sum_exec_time / self.count,
            avg_user_satisfaction=self.sum_satisfaction / self.count,
            total_executions=self.count,
            user_count=1,
            optimization_count=0,
            time_range_start=start,
            time_range_end=end,
        )


class _GlobalStats:
    """Internal: Global running statistics"""

    def __init__(self):
        self.total_executions = 0
