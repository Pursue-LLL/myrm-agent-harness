"""Evolution success rate tracking and reporting (收益6/10).

Aggregates evolution metrics across all skills for system-level insights.
Simplified from OpenSpace's time-series metrics database.

[INPUT]
- agent.skills.evolution.core.types::EvolutionType (POS: Data types for skill evolution system.)

[OUTPUT]
- EvolutionMetrics: Aggregated evolution metrics.
- EvolutionMetricsTracker: Track and report evolution success rates across system.
- get_metrics_tracker: Get or create global metrics tracker instance.

[POS]
Aggregates evolution metrics across all skills for system-level insights.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from myrm_agent_harness.agent.skills.evolution.core.types import EvolutionType

logger = logging.getLogger(__name__)


@dataclass
class EvolutionMetrics:
    """Aggregated evolution metrics."""

    total_evolutions: int = 0
    successful_evolutions: int = 0
    failed_evolutions: int = 0

    # Per-type breakdown
    fix_count: int = 0
    fix_success: int = 0
    derived_count: int = 0
    derived_success: int = 0
    captured_count: int = 0
    captured_success: int = 0

    # Timing
    first_evolution: datetime | None = None
    last_evolution: datetime | None = None

    # Tool usage metrics (Scheme E)
    tool_call_count: int = 0
    tool_call_time: float = 0.0
    tool_errors: int = 0

    # Summarization metrics (Scheme E)
    summarization_count: int = 0
    summarization_time: float = 0.0
    token_saved: int = 0

    @property
    def success_rate(self) -> float:
        """Overall success rate."""
        if self.total_evolutions == 0:
            return 0.0
        return self.successful_evolutions / self.total_evolutions

    @property
    def fix_success_rate(self) -> float:
        """FIX evolution success rate."""
        if self.fix_count == 0:
            return 0.0
        return self.fix_success / self.fix_count

    @property
    def derived_success_rate(self) -> float:
        """DERIVED evolution success rate."""
        if self.derived_count == 0:
            return 0.0
        return self.derived_success / self.derived_count

    @property
    def captured_success_rate(self) -> float:
        """CAPTURED evolution success rate."""
        if self.captured_count == 0:
            return 0.0
        return self.captured_success / self.captured_count


class EvolutionMetricsTracker:
    """Track and report evolution success rates across system."""

    def __init__(self):
        """Initialize metrics tracker."""
        self._metrics = EvolutionMetrics()

        # Per-skill metrics (for debugging)
        self._per_skill_metrics: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "success": 0})

    def record_evolution(self, skill_id: str, evolution_type: EvolutionType, success: bool) -> None:
        """Record evolution result.

        Args:
            skill_id: Skill that was evolved
            evolution_type: Type of evolution
            success: Whether evolution succeeded
        """
        now = datetime.now()

        # Update global metrics
        self._metrics.total_evolutions += 1
        if success:
            self._metrics.successful_evolutions += 1
        else:
            self._metrics.failed_evolutions += 1

        # Update timing
        if self._metrics.first_evolution is None:
            self._metrics.first_evolution = now
        self._metrics.last_evolution = now

        # Update per-type metrics
        if evolution_type == EvolutionType.FIX:
            self._metrics.fix_count += 1
            if success:
                self._metrics.fix_success += 1
        elif evolution_type == EvolutionType.DERIVED:
            self._metrics.derived_count += 1
            if success:
                self._metrics.derived_success += 1
        elif evolution_type == EvolutionType.CAPTURED:
            self._metrics.captured_count += 1
            if success:
                self._metrics.captured_success += 1

        # Update per-skill metrics
        self._per_skill_metrics[skill_id]["total"] += 1
        if success:
            self._per_skill_metrics[skill_id]["success"] += 1

        logger.debug("Evolution recorded: %s/%s success=%s", skill_id, evolution_type, success)

    def record_tool_call(self, tool_name: str, elapsed_time: float, success: bool) -> None:
        """Record tool call metrics.

        Args:
            tool_name: Name of tool that was called
            elapsed_time: Time taken for tool execution (seconds)
            success: Whether tool call succeeded
        """
        self._metrics.tool_call_count += 1
        self._metrics.tool_call_time += elapsed_time

        if not success:
            self._metrics.tool_errors += 1

        logger.debug("Tool call recorded: %s time=%.2fs success=%s", tool_name, elapsed_time, success)

    def record_summarization(self, original_length: int, summarized_length: int, elapsed_time: float) -> None:
        """Record summarization metrics.

        Args:
            original_length: Length of original content (chars)
            summarized_length: Length of summarized content (chars)
            elapsed_time: Time taken for summarization (seconds)
        """
        self._metrics.summarization_count += 1
        self._metrics.summarization_time += elapsed_time

        # Estimate token savings (rough: 1 token ≈ 4 chars)
        token_saved = (original_length - summarized_length) // 4
        self._metrics.token_saved += token_saved

        logger.debug(
            "Summarization recorded: %d -> %d chars (%.1f%% reduction), ~%d tokens saved",
            original_length,
            summarized_length,
            (1 - summarized_length / original_length) * 100,
            token_saved,
        )

    def get_metrics(self) -> EvolutionMetrics:
        """Get current metrics snapshot."""
        return self._metrics

    def get_report(self) -> dict[str, Any]:
        """Generate detailed metrics report.

        Returns:
            Dict with aggregated metrics and rates
        """
        return {
            "summary": {
                "total": self._metrics.total_evolutions,
                "success": self._metrics.successful_evolutions,
                "failed": self._metrics.failed_evolutions,
                "success_rate": f"{self._metrics.success_rate:.1%}",
            },
            "by_type": {
                "fix": {
                    "count": self._metrics.fix_count,
                    "success": self._metrics.fix_success,
                    "rate": f"{self._metrics.fix_success_rate:.1%}",
                },
                "derived": {
                    "count": self._metrics.derived_count,
                    "success": self._metrics.derived_success,
                    "rate": f"{self._metrics.derived_success_rate:.1%}",
                },
                "captured": {
                    "count": self._metrics.captured_count,
                    "success": self._metrics.captured_success,
                    "rate": f"{self._metrics.captured_success_rate:.1%}",
                },
            },
            "timing": {
                "first_evolution": self._metrics.first_evolution.isoformat() if self._metrics.first_evolution else None,
                "last_evolution": self._metrics.last_evolution.isoformat() if self._metrics.last_evolution else None,
            },
            "skills_evolved": len(self._per_skill_metrics),
            "tool_usage": {
                "total_calls": self._metrics.tool_call_count,
                "total_time": f"{self._metrics.tool_call_time:.2f}s",
                "avg_time_per_call": f"{self._metrics.tool_call_time / self._metrics.tool_call_count:.2f}s"
                if self._metrics.tool_call_count > 0
                else "N/A",
                "error_count": self._metrics.tool_errors,
                "error_rate": f"{self._metrics.tool_errors / self._metrics.tool_call_count:.1%}"
                if self._metrics.tool_call_count > 0
                else "N/A",
            },
            "summarization": {
                "count": self._metrics.summarization_count,
                "total_time": f"{self._metrics.summarization_time:.2f}s",
                "avg_time": f"{self._metrics.summarization_time / self._metrics.summarization_count:.2f}s"
                if self._metrics.summarization_count > 0
                else "N/A",
                "token_saved": self._metrics.token_saved,
                "token_saved_per_summary": f"{self._metrics.token_saved / self._metrics.summarization_count:.0f}"
                if self._metrics.summarization_count > 0
                else "N/A",
            },
        }

    def get_top_skills(self, limit: int = 10) -> list[tuple[str, float, int]]:
        """Get skills with most successful evolutions.

        Args:
            limit: Max skills to return

        Returns:
            List of (skill_id, success_rate, total_evolutions) tuples
        """
        results: list[tuple[str, float, int]] = []

        for skill_id, metrics in self._per_skill_metrics.items():
            total = metrics["total"]
            success = metrics["success"]
            rate = success / total if total > 0 else 0.0

            results.append((skill_id, rate, total))

        # Sort by total evolutions (descending)
        results.sort(key=lambda x: x[2], reverse=True)
        return results[:limit]

    def reset(self) -> None:
        """Reset all metrics."""
        self._metrics = EvolutionMetrics()
        self._per_skill_metrics.clear()
        logger.info("Evolution metrics reset")


# Global tracker instance
_global_metrics_tracker: EvolutionMetricsTracker | None = None


def get_metrics_tracker() -> EvolutionMetricsTracker:
    """Get or create global metrics tracker instance."""
    global _global_metrics_tracker

    if _global_metrics_tracker is None:
        _global_metrics_tracker = EvolutionMetricsTracker()

    return _global_metrics_tracker
