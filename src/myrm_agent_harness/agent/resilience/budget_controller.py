"""Dynamic execution budget and quota circuit breaker controller.

Monitors token consumption rate, step quotas, consecutive error counts,
and prevents runaways/stagnation during multi-hour marathon tasks.

[INPUT]
- .types: ExecutionBudgetConfig

[OUTPUT]
- DynamicExecutionBudgetController: State tracker and safety governor for agent execution.

[POS]
Harness resilience budget subsystem ensuring safe, cost-controlled execution.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from myrm_agent_harness.agent.resilience.types import ExecutionBudgetConfig
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


@dataclass(slots=True)
class ExecutionBudgetSnapshot:
    """Current snapshot of execution budget usage."""

    total_steps: int
    total_tokens: int
    consecutive_errors: int
    elapsed_seconds: float
    is_exhausted: bool
    exhaustion_reason: str | None = None
    recent_token_velocity: float = 0.0  # tokens/sec in current window


class DynamicExecutionBudgetController:
    """Dynamic execution budget controller for marathon agent runs."""

    def __init__(self, config: ExecutionBudgetConfig | None = None) -> None:
        self.config = config or ExecutionBudgetConfig()
        self._start_time: float = time.monotonic()
        self._total_steps: int = 0
        self._total_tokens: int = 0
        self._consecutive_errors: int = 0
        self._token_window: list[tuple[float, int]] = []  # (timestamp, tokens)
        self._last_progress_time: float = self._start_time

    def record_step(self, step_name: str | None = None) -> None:
        """Record a single execution step and update progress timestamp."""
        self._total_steps += 1
        self._last_progress_time = time.monotonic()

    def record_token_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Record token usage and maintain sliding window for velocity tracking."""
        total = prompt_tokens + completion_tokens
        self._total_tokens += total
        now = time.monotonic()
        self._token_window.append((now, total))
        self._prune_token_window(now)

    def record_error(self, error: Exception | str) -> None:
        """Record an execution failure."""
        self._consecutive_errors += 1
        logger.warning(
            "DynamicExecutionBudgetController recorded failure: count=%d/%d err=%s",
            self._consecutive_errors,
            self.config.max_consecutive_errors,
            str(error)[:100],
        )

    def record_success(self) -> None:
        """Reset consecutive errors on successful execution."""
        if self._consecutive_errors > 0:
            logger.info("DynamicExecutionBudgetController consecutive errors reset from %d to 0", self._consecutive_errors)
            self._consecutive_errors = 0

    def check_budget_violation(self) -> str | None:
        """Check if any budget, time, or error limit has been breached."""
        now = time.monotonic()
        elapsed = now - self._start_time

        # 1. Step quota check
        if self._total_steps >= self.config.max_steps_per_task:
            return f"Step quota exceeded: {self._total_steps}/{self.config.max_steps_per_task} steps"

        # 2. Token budget check
        if self._total_tokens >= self.config.max_tokens_total:
            return f"Token budget exceeded: {self._total_tokens}/{self.config.max_tokens_total} tokens"

        # 3. Consecutive error breaker
        if self._consecutive_errors >= self.config.max_consecutive_errors:
            return (
                f"Consecutive error breaker tripped: {self._consecutive_errors}/"
                f"{self.config.max_consecutive_errors} failures without recovery"
            )

        # 4. Total duration check
        if elapsed >= self.config.max_duration_seconds:
            return f"Execution duration exceeded: {elapsed:.1f}s/{self.config.max_duration_seconds:.1f}s"

        return None

    def get_snapshot(self) -> ExecutionBudgetSnapshot:
        """Return a structured snapshot of current budget state."""
        now = time.monotonic()
        self._prune_token_window(now)
        elapsed = now - self._start_time
        violation = self.check_budget_violation()

        window_tokens = sum(t for _, t in self._token_window)
        window_duration = (self._token_window[-1][0] - self._token_window[0][0]) if len(self._token_window) > 1 else 1.0
        velocity = (window_tokens / max(window_duration, 1.0)) if self._token_window else 0.0

        return ExecutionBudgetSnapshot(
            total_steps=self._total_steps,
            total_tokens=self._total_tokens,
            consecutive_errors=self._consecutive_errors,
            elapsed_seconds=elapsed,
            is_exhausted=violation is not None,
            exhaustion_reason=violation,
            recent_token_velocity=velocity,
        )

    def _prune_token_window(self, now: float, window_seconds: float = 300.0) -> None:
        """Prune token entries older than window_seconds."""
        cutoff = now - window_seconds
        self._token_window = [(t, val) for t, val in self._token_window if t >= cutoff]
