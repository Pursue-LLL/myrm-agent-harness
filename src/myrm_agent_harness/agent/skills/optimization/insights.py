"""Insights Analytics System

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- .protocols.SkillExecutionProvider (POS: 执行事件提供者)
- .protocols.SkillOptimizationStorage (POS: 存储层接口)
- datetime (POS: 时间处理)

[OUTPUT]
- InsightsAnalyzer: Insights分析器类
- ToolUsageInsight: 工具使用洞察数据类
- ActivityPattern: 活动模式数据类
- TopSession: Top Session数据类

[POS]
Insights analysis system (framework layer). Provides deep statistical analysis of skill executions.

"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .protocols import SkillExecutionProvider, SkillOptimizationStorage


@dataclass
class ToolUsageInsight:
    """工具使用洞察

    Attributes:
        skill_id: Skill ID
        total_calls: 总调用次数
        success_count: 成功次数
        failed_count: 失败次数
        success_rate: 成功率（0.0-1.0）
        avg_duration_seconds: 平均耗时（秒）
        avg_token_count: 平均token消耗
        total_token_count: 总token消耗
        last_used_at: 最后使用时间
    """

    skill_id: str
    total_calls: int
    success_count: int
    failed_count: int
    success_rate: float
    avg_duration_seconds: float
    avg_token_count: float
    total_token_count: int
    last_used_at: datetime | None = None


@dataclass
class ActivityPattern:
    """活动模式

    Attributes:
        skill_id: Skill ID
        hourly_distribution: 小时分布（0-23小时的调用次数）
        weekday_distribution: 星期分布（0-6，周一到周日的调用次数）
        peak_hour: 峰值小时（调用最多的小时）
        peak_weekday: 峰值星期（调用最多的星期）
    """

    skill_id: str
    hourly_distribution: dict[int, int]
    weekday_distribution: dict[int, int]
    peak_hour: int
    peak_weekday: int


@dataclass
class TopSession:
    """Top Session

    Attributes:
        session_id: Session ID
        skill_count: 使用的skill数量
        total_calls: 总调用次数
        total_token_count: 总token消耗
        duration_seconds: 会话持续时间（秒）
        started_at: 开始时间
        ended_at: 结束时间
    """

    session_id: str
    skill_count: int
    total_calls: int
    total_token_count: int
    duration_seconds: float
    started_at: datetime
    ended_at: datetime


class InsightsAnalyzer:
    """Insights分析器

    提供skill执行的深度统计分析。

    Args:
        execution_provider: 执行数据提供者
        storage: 存储层（可选，用于缓存）
    """

    def __init__(self, execution_provider: SkillExecutionProvider, storage: SkillOptimizationStorage | None = None):
        self.execution_provider = execution_provider
        self.storage = storage

    async def get_tool_usage_insights(self, days: int = 7, min_calls: int = 1) -> list[ToolUsageInsight]:
        """获取工具使用洞察

        Args:
            days: 统计最近N天
            min_calls: 最小调用次数过滤（避免噪音）

        Returns:
            工具使用洞察列表，按total_calls降序
        """
        skill_ids = await self.execution_provider.get_all_skill_ids()
        insights: list[ToolUsageInsight] = []

        for skill_id in skill_ids:
            samples = await self.execution_provider.get_skill_executions(skill_id=skill_id, days=days)

            if len(samples) < min_calls:
                continue

            total_calls = len(samples)
            success_count = sum(1 for s in samples if s.success)
            failed_count = total_calls - success_count
            success_rate = success_count / total_calls if total_calls > 0 else 0.0

            total_duration = sum(s.duration_seconds for s in samples)
            avg_duration = total_duration / total_calls if total_calls > 0 else 0.0

            total_tokens = sum(s.token_count for s in samples)
            avg_tokens = total_tokens / total_calls if total_calls > 0 else 0.0

            last_used = max((s.executed_at for s in samples), default=None)

            insights.append(
                ToolUsageInsight(
                    skill_id=skill_id,
                    total_calls=total_calls,
                    success_count=success_count,
                    failed_count=failed_count,
                    success_rate=success_rate,
                    avg_duration_seconds=avg_duration,
                    avg_token_count=avg_tokens,
                    total_token_count=total_tokens,
                    last_used_at=last_used,
                )
            )

        insights.sort(key=lambda x: x.total_calls, reverse=True)
        return insights

    async def get_activity_patterns(self, skill_id: str, days: int = 30) -> ActivityPattern | None:
        """获取活动模式

        Args:
            skill_id: Skill ID
            days: 统计最近N天

        Returns:
            活动模式对象，无数据返回None
        """
        samples = await self.execution_provider.get_skill_executions(skill_id=skill_id, days=days)

        if not samples:
            return None

        hourly_dist: dict[int, int] = defaultdict(int)
        weekday_dist: dict[int, int] = defaultdict(int)

        for sample in samples:
            hour = sample.executed_at.hour
            weekday = sample.executed_at.weekday()

            hourly_dist[hour] += 1
            weekday_dist[weekday] += 1

        peak_hour = max(hourly_dist.items(), key=lambda x: x[1])[0]
        peak_weekday = max(weekday_dist.items(), key=lambda x: x[1])[0]

        return ActivityPattern(
            skill_id=skill_id,
            hourly_distribution=dict(hourly_dist),
            weekday_distribution=dict(weekday_dist),
            peak_hour=peak_hour,
            peak_weekday=peak_weekday,
        )

    async def get_top_sessions(self, days: int = 7, limit: int = 10, sort_by: str = "total_calls") -> list[TopSession]:
        """获取Top Sessions

        Args:
            days: 统计最近N天
            limit: 返回数量
            sort_by: 排序字段（"total_calls" | "total_token_count" | "duration_seconds"）

        Returns:
            Top Session列表，按sort_by降序
        """
        skill_ids = await self.execution_provider.get_all_skill_ids()
        session_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "skill_ids": set(),
                "total_calls": 0,
                "total_tokens": 0,
                "min_time": None,
                "max_time": None,
            }
        )

        for skill_id in skill_ids:
            samples = await self.execution_provider.get_skill_executions(skill_id=skill_id, days=days)

            for sample in samples:
                if not sample.session_id:
                    continue

                session_id = sample.session_id
                session_stats[session_id]["skill_ids"].add(skill_id)
                session_stats[session_id]["total_calls"] += 1
                session_stats[session_id]["total_tokens"] += sample.token_count

                if (
                    session_stats[session_id]["min_time"] is None
                    or sample.executed_at < session_stats[session_id]["min_time"]
                ):
                    session_stats[session_id]["min_time"] = sample.executed_at

                if (
                    session_stats[session_id]["max_time"] is None
                    or sample.executed_at > session_stats[session_id]["max_time"]
                ):
                    session_stats[session_id]["max_time"] = sample.executed_at

        top_sessions: list[TopSession] = []

        for session_id, stats in session_stats.items():
            if stats["min_time"] is None or stats["max_time"] is None:
                continue

            duration = (stats["max_time"] - stats["min_time"]).total_seconds()

            top_sessions.append(
                TopSession(
                    session_id=session_id,
                    skill_count=len(stats["skill_ids"]),
                    total_calls=stats["total_calls"],
                    total_token_count=stats["total_tokens"],
                    duration_seconds=duration,
                    started_at=stats["min_time"],
                    ended_at=stats["max_time"],
                )
            )

        if sort_by == "total_calls":
            top_sessions.sort(key=lambda x: x.total_calls, reverse=True)
        elif sort_by == "total_token_count":
            top_sessions.sort(key=lambda x: x.total_token_count, reverse=True)
        elif sort_by == "duration_seconds":
            top_sessions.sort(key=lambda x: x.duration_seconds, reverse=True)

        return top_sessions[:limit]

    async def get_summary_stats(self, days: int = 7) -> dict[str, Any]:
        """获取汇总统计

        Args:
            days: 统计最近N天

        Returns:
            汇总统计字典

        Examples:
            >>> stats = await analyzer.get_summary_stats(days=7)
            >>> stats
            {
                "total_skills": 42,
                "active_skills": 38,
                "total_calls": 1543,
                "success_rate": 0.95,
                "avg_duration_seconds": 2.3,
                "total_token_count": 152890
            }
        """
        insights = await self.get_tool_usage_insights(days=days, min_calls=1)

        total_skills = await self.execution_provider.get_all_skill_ids()
        active_skills = [i for i in insights if i.total_calls > 0]

        total_calls = sum(i.total_calls for i in insights)
        total_success = sum(i.success_count for i in insights)
        total_tokens = sum(i.total_token_count for i in insights)

        success_rate = total_success / total_calls if total_calls > 0 else 0.0

        weighted_duration = sum(i.avg_duration_seconds * i.total_calls for i in insights)
        avg_duration = weighted_duration / total_calls if total_calls > 0 else 0.0

        return {
            "total_skills": len(total_skills),
            "active_skills": len(active_skills),
            "total_calls": total_calls,
            "success_rate": success_rate,
            "avg_duration_seconds": avg_duration,
            "total_token_count": total_tokens,
        }
