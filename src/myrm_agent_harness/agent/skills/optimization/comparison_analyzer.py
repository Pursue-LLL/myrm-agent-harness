"""Comparison Analyzer

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- .protocols.SkillQualityAggregator (POS: 聚合Protocol)
- .types.ComparisonResult (POS: 对比结果类型)

[OUTPUT]
- ComparisonAnalyzer: 对比分析器

[POS]
Comparison analysis tool (framework layer). Supports multi-dimensional comparison: before/after, version-to-version, and user-to-user.

"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from .protocols import SkillQualityAggregator
from .types import ComparisonResult, SkillQualityAggregate

if TYPE_CHECKING:
    pass


class ComparisonAnalyzer:
    """Comparison Analyzer for Skill Quality

    Multi-dimensional comparison tool for validating optimization impact.

    Supported Comparison Scenarios:
    1. Before/After Optimization: Validate optimization effectiveness
    2. Version Comparison: Compare quality across skill versions
    3. Time Period Comparison: Compare current vs historical performance
    4. User Comparison: Compare quality across different users (future)

    Features:
    - Delta calculation: Quality, success rate, token efficiency
    - Improvement percentage: Quantify optimization impact
    - Statistical significance: Ensure comparisons are meaningful
    - Flexible time ranges: Custom before/after windows

    Design:
    - Framework-level: No business logic, pure computation
    - Aggregator-agnostic: Works with any SkillQualityAggregator
    - Type-safe: Complete type hints for IDE support

    Usage:
        ```python
        from myrm_agent_harness.agent.skills.optimization import (
            InMemoryAggregator,
            ComparisonAnalyzer)

        aggregator = InMemoryAggregator(storage)
        analyzer = ComparisonAnalyzer(aggregator)

        # Compare optimization impact
        results = await analyzer.compare_optimization_impact(
            skill_id="pdf-generator",
            before_days=30,
            after_days=7)

        for result in results:
            print(f"Improvement: {result.improvement_pct:.1f}%")

        # Compare versions
        version_results = await analyzer.compare_versions(
            skill_id="pdf-generator",
            version_a=1,
            version_b=2)
        ```
    """

    def __init__(self, aggregator: SkillQualityAggregator):
        """Initialize comparison analyzer

        Args:
            aggregator: SkillQualityAggregator for data access
        """
        self._aggregator = aggregator

    async def compare_optimization_impact(
        self, skill_id: str, before_days: int = 30, after_days: int = 7
    ) -> list[ComparisonResult]:
        """Compare skill quality before/after optimization

        Args:
            skill_id: Skill to analyze
            before_days: Days ago for "before" snapshot (e.g., 30 = last 30 days)
            after_days: Days ago for "after" snapshot (e.g., 7 = last 7 days, 0 = now)

        Returns:
            List of ComparisonResult showing improvement metrics

        Example:
            ```python
            # Compare last 30 days vs last 7 days
            results = await analyzer.compare_optimization_impact(
                skill_id="pdf-generator",
                before_days=30,
                after_days=7)

            if results:
                result = results[0]
                if result.improvement_pct > 10:
                    print("Significant improvement detected!")
            ```
        """
        return await self._aggregator.compare(
            before_range_days=before_days, after_range_days=after_days, skill_id=skill_id
        )

    async def compare_time_periods(
        self, skill_id: str | None = None, period1_days: int = 60, period2_days: int = 30
    ) -> list[ComparisonResult]:
        """Compare quality across two time periods

        Args:
            skill_id: Optional skill filter, None compares all skills
            period1_days: Days ago for period 1 start
            period2_days: Days ago for period 2 start

        Returns:
            List of ComparisonResult sorted by improvement percentage

        Example:
            ```python
            # Compare Q1 vs Q2 (assuming today is mid-year)
            results = await analyzer.compare_time_periods(
                skill_id=None,  # All skills
                period1_days=180,  # 6 months ago
                period2_days=90,   # 3 months ago
            )

            top_improved = results[:5]  # Top 5 improved skills
            ```
        """
        return await self._aggregator.compare(
            before_range_days=period1_days, after_range_days=period2_days, skill_id=skill_id
        )

    async def compare_versions(self, skill_id: str, version_a: int, version_b: int) -> ComparisonResult | None:
        """Compare quality between two skill versions

        Note: This requires storage layer to support per-version quality snapshots.
        Current implementation falls back to time-based comparison.

        Args:
            skill_id: Skill to analyze
            version_a: Baseline version number
            version_b: Candidate version number

        Returns:
            ComparisonResult or None if insufficient data

        Example:
            ```python
            result = await analyzer.compare_versions(
                skill_id="pdf-generator",
                version_a=1,
                version_b=2)

            if result and result.improvement_pct > 5:
                print(f"Version {version_b} is {result.improvement_pct:.1f}% better")
            ```
        """
        results = await self._aggregator.compare(before_range_days=60, after_range_days=30, skill_id=skill_id)

        return results[0] if results else None

    async def find_top_improvements(self, limit: int = 10, time_range_days: int = 30) -> list[ComparisonResult]:
        """Find skills with highest quality improvements

        Args:
            limit: Maximum number of results
            time_range_days: Time window for comparison

        Returns:
            List of ComparisonResult sorted by improvement percentage descending

        Example:
            ```python
            top_improved = await analyzer.find_top_improvements(limit=10)

            for result in top_improved:
                print(f"{result.after.skill_id}: +{result.improvement_pct:.1f}%")
            ```
        """
        results = await self._aggregator.compare(
            before_range_days=time_range_days * 2, after_range_days=time_range_days, skill_id=None
        )

        results.sort(key=lambda x: x.improvement_pct, reverse=True)
        return results[:limit]

    async def find_top_regressions(self, limit: int = 10, time_range_days: int = 30) -> list[ComparisonResult]:
        """Find skills with highest quality regressions

        Args:
            limit: Maximum number of results
            time_range_days: Time window for comparison

        Returns:
            List of ComparisonResult sorted by improvement percentage ascending

        Example:
            ```python
            regressions = await analyzer.find_top_regressions(limit=10)

            for result in regressions:
                if result.improvement_pct < -10:
                    print(f"ALERT: {result.after.skill_id} regressed by {result.improvement_pct:.1f}%")
            ```
        """
        results = await self._aggregator.compare(
            before_range_days=time_range_days * 2, after_range_days=time_range_days, skill_id=None
        )

        results.sort(key=lambda x: x.improvement_pct)
        return results[:limit]

    async def compare_aggregate_stats(
        self, before: SkillQualityAggregate, after: SkillQualityAggregate
    ) -> ComparisonResult:
        """Compare two aggregate statistics directly

        Args:
            before: Baseline aggregate
            after: Current aggregate

        Returns:
            ComparisonResult with delta metrics

        Example:
            ```python
            aggregator = InMemoryAggregator(storage)
            analyzer = ComparisonAnalyzer(aggregator)

            before = await aggregator.aggregate_by_skill("pdf-generator", time_range_days=60)[0]
            after = await aggregator.aggregate_by_skill("pdf-generator", time_range_days=30)[0]

            result = await analyzer.compare_aggregate_stats(before, after)
            print(f"Delta quality: {result.delta_quality:.3f}")
            ```
        """
        delta_quality = after.avg_quality_score - before.avg_quality_score
        delta_sr = after.avg_success_rate - before.avg_success_rate
        delta_te = after.avg_token_efficiency - before.avg_token_efficiency

        improvement_pct = (delta_quality / before.avg_quality_score * 100) if before.avg_quality_score > 0 else 0.0

        return ComparisonResult(
            before=before,
            after=after,
            delta_quality=delta_quality,
            delta_success_rate=delta_sr,
            delta_token_efficiency=delta_te,
            improvement_pct=improvement_pct,
            compared_at=datetime.now(),
        )
