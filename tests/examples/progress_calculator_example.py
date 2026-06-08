"""Reference ProgressCalculator implementations for sub-agent progress reporting.

Moved out of ``src/`` — examples belong in the test tree, not the distributable package.

[OUTPUT]
- WeightedTaskProgressCalculator: weighted progress by task type/complexity
- TimeBasedProgressCalculator: time-based progress when duration is known

[POS]
Custom ProgressCalculator reference for docs and integration tests.
"""

from __future__ import annotations


class WeightedTaskProgressCalculator:
    """Weighted task progress calculator for heterogeneous sub-agent workloads."""

    def __init__(self, task_type: str = "default", complexity_weight: float = 1.0) -> None:
        self.task_type = task_type
        self.complexity_weight = complexity_weight

        self.task_type_rates = {
            "research": 50,
            "coding": 100,
            "review": 150,
            "planning": 80,
            "default": 100,
        }

    def calculate_progress(
        self, current_tokens: int, budget_tokens: int | None, tool_count: int, elapsed_seconds: float
    ) -> dict[str, object]:
        if budget_tokens:
            base_progress = min(1.0, current_tokens / budget_tokens)
            is_estimated = False
        else:
            base_progress = min(1.0, tool_count / 8.0)
            is_estimated = True

        weighted_progress = min(1.0, base_progress * self.complexity_weight)

        eta_seconds = None
        eta_readable = None

        if budget_tokens and elapsed_seconds > 0:
            estimated_rate = self.task_type_rates.get(self.task_type, 100)
            actual_rate = current_tokens / elapsed_seconds if elapsed_seconds > 0 else estimated_rate
            blended_rate = actual_rate * 0.7 + estimated_rate * 0.3
            remaining_tokens = budget_tokens - current_tokens
            if remaining_tokens > 0 and blended_rate > 0:
                eta_seconds = int((remaining_tokens / blended_rate) * self.complexity_weight)
                if eta_seconds > 60:
                    mins = eta_seconds // 60
                    secs = eta_seconds % 60
                    eta_readable = f"{mins}m{secs}s"
                else:
                    eta_readable = f"{eta_seconds}s"

        progress_data: dict[str, object] = {
            "progress": weighted_progress,
            "current_tokens": current_tokens,
            "budget_tokens": budget_tokens,
            "tool_count": tool_count,
            "is_estimated": is_estimated,
            "current_step": f"{self.task_type} task",
            "task_type": self.task_type,
            "complexity_weight": self.complexity_weight,
        }

        if eta_seconds is not None:
            progress_data["eta_seconds"] = eta_seconds
            progress_data["eta_readable"] = eta_readable

        return progress_data


class TimeBasedProgressCalculator:
    """Time-based progress calculator when total duration is known upfront."""

    def __init__(self, estimated_duration_seconds: float) -> None:
        self.estimated_duration_seconds = estimated_duration_seconds

    def calculate_progress(
        self, current_tokens: int, budget_tokens: int | None, tool_count: int, elapsed_seconds: float
    ) -> dict[str, object]:
        progress = min(1.0, elapsed_seconds / self.estimated_duration_seconds)

        eta_seconds = None
        eta_readable = None
        if progress < 1.0:
            eta_seconds = int(self.estimated_duration_seconds - elapsed_seconds)
            if eta_seconds > 60:
                mins = eta_seconds // 60
                secs = eta_seconds % 60
                eta_readable = f"{mins}m{secs}s"
            else:
                eta_readable = f"{eta_seconds}s"

        progress_data: dict[str, object] = {
            "progress": progress,
            "current_tokens": current_tokens,
            "budget_tokens": budget_tokens,
            "tool_count": tool_count,
            "is_estimated": True,
            "current_step": f"elapsed {int(elapsed_seconds)}s / {int(self.estimated_duration_seconds)}s",
            "calculation_method": "time-based",
        }

        if eta_seconds is not None:
            progress_data["eta_seconds"] = eta_seconds
            progress_data["eta_readable"] = eta_readable

        return progress_data
