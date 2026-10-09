# [INPUT]: LongTaskIterationSnapshot from roll_forward_types
# [OUTPUT]: LongTaskTelemetryTracker
# [POS]: myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.long_task_telemetry
"""Long-horizon task telemetry tracker and iteration versioning HUD (Item 330).

Maintains telemetry across autonomous multi-hour workflows, version iterations
(e.g., V1 -> V10 -> V13), cache hit rates, cost economics, and preview assets.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Final

from myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.roll_forward_types import (
    LongTaskIterationSnapshot,
)


class LongTaskTelemetryTracker:
    """Thread-safe telemetry aggregator for long-running autonomous workflows."""

    def __init__(self, task_id: str, weekly_quota_tokens: int = 50_000_000) -> None:
        self._lock = threading.RLock()
        self._task_id: Final[str] = task_id
        self._weekly_quota_tokens: Final[int] = weekly_quota_tokens
        self._snapshots: list[LongTaskIterationSnapshot] = []
        self._cumulative_input_tokens: int = 0
        self._cumulative_cache_read_tokens: int = 0
        self._cumulative_cost_saved_usd: float = 0.0
        self._latest_preview_path: str = ""
        self._current_version_label: str = "V0"

    @property
    def task_id(self) -> str:
        """Unique task identifier."""
        return self._task_id

    @property
    def current_version(self) -> str:
        """Current iteration version tag."""
        with self._lock:
            return self._current_version_label

    def record_iteration(
        self,
        iteration_label: str,
        tool_round_index: int,
        input_tokens: int,
        cache_read_tokens: int,
        cost_saved_usd: float,
        preview_artifact_path: str = "",
        now: datetime | None = None,
    ) -> LongTaskIterationSnapshot:
        """Record an iteration milestone (e.g. V1 -> V10) during autonomous execution."""
        ts = now or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        with self._lock:
            hit_rate = (
                cache_read_tokens / float(input_tokens)
                if input_tokens > 0
                else 0.0
            )
            hit_rate = max(0.0, min(1.0, hit_rate))

            snapshot = LongTaskIterationSnapshot(
                iteration_label=iteration_label,
                tool_round_index=tool_round_index,
                cache_hit_rate=round(hit_rate, 4),
                input_tokens=input_tokens,
                cache_read_tokens=cache_read_tokens,
                cost_saved_usd=round(cost_saved_usd, 6),
                preview_artifact_path=preview_artifact_path,
                timestamp_iso=ts.isoformat(),
            )

            self._snapshots.append(snapshot)
            self._cumulative_input_tokens += input_tokens
            self._cumulative_cache_read_tokens += cache_read_tokens
            self._cumulative_cost_saved_usd = round(
                self._cumulative_cost_saved_usd + cost_saved_usd, 6
            )
            self._current_version_label = iteration_label
            if preview_artifact_path:
                self._latest_preview_path = preview_artifact_path

            return snapshot

    def get_mobile_telemetry_hud(self) -> dict[str, str | int | float | list[dict[str, str | float | int]]]:
        """Produce lightweight HUD payload tailored for mobile and desktop status cards."""
        with self._lock:
            total_in = self._cumulative_input_tokens
            total_cached = self._cumulative_cache_read_tokens
            overall_hit_rate = (
                total_cached / float(total_in)
                if total_in > 0
                else 0.0
            )
            quota_percentage = (
                (total_in / float(self._weekly_quota_tokens)) * 100.0
                if self._weekly_quota_tokens > 0
                else 0.0
            )

            recent_curve: list[dict[str, str | float | int]] = [
                {
                    "label": s.iteration_label,
                    "round": s.tool_round_index,
                    "hit_rate": s.cache_hit_rate,
                    "input_tokens": s.input_tokens,
                }
                for s in self._snapshots[-10:]
            ]

            return {
                "task_id": self._task_id,
                "current_version": self._current_version_label,
                "total_iterations": len(self._snapshots),
                "total_input_tokens": total_in,
                "total_cache_read_tokens": total_cached,
                "overall_cache_hit_rate": round(overall_hit_rate, 4),
                "weekly_quota_percentage": round(quota_percentage, 2),
                "cumulative_cost_saved_usd": self._cumulative_cost_saved_usd,
                "latest_preview_path": self._latest_preview_path,
                "recent_trend": recent_curve,
            }

    def reset(self) -> None:
        """Reset task telemetry history."""
        with self._lock:
            self._snapshots.clear()
            self._cumulative_input_tokens = 0
            self._cumulative_cache_read_tokens = 0
            self._cumulative_cost_saved_usd = 0.0
            self._latest_preview_path = ""
            self._current_version_label = "V0"
