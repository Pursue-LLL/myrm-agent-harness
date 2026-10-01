"""Promotion gate calculator with fixed-capacity sliding window.

[INPUT]
- models.py: AutonomyLevel, AutonomyMetrics, AutonomyPromotionResult

[OUTPUT]
- PromotionGateCalculator: thread-safe, deterministic metrics evaluator

[POS]
Quantifies agent operational reliability over sliding window.
Prevents early false promotion via minimum sample thresholds, and
guards against Goodhart's law by requiring non-trivial mutation actions.
"""

from __future__ import annotations

import collections
import threading
import time
from dataclasses import dataclass
from typing import Final

from myrm_agent_harness.core.security.autonomy.models import (
    AutonomyLevel,
    AutonomyMetrics,
    AutonomyPromotionResult,
)

DEFAULT_WINDOW_CAPACITY: Final[int] = 50
DEFAULT_MIN_SAMPLES_FOR_PROMOTION: Final[int] = 20
DEFAULT_REQUIRED_SUCCESS_RATE: Final[float] = 0.98
DEFAULT_REQUIRED_MUTATION_RATIO: Final[float] = 0.20


@dataclass(frozen=True, slots=True)
class _InvocationRecord:
    is_success: bool
    is_destructive: bool
    is_violation: bool
    timestamp: float


class PromotionGateCalculator:
    """Sliding-window metrics calculator and autonomy promotion evaluator."""

    def __init__(
        self,
        capacity: int = DEFAULT_WINDOW_CAPACITY,
        min_samples: int = DEFAULT_MIN_SAMPLES_FOR_PROMOTION,
        required_success_rate: float = DEFAULT_REQUIRED_SUCCESS_RATE,
        required_mutation_ratio: float = DEFAULT_REQUIRED_MUTATION_RATIO,
    ) -> None:
        self._capacity: Final[int] = max(10, capacity)
        self._min_samples: Final[int] = max(5, min_samples)
        self._required_success_rate: Final[float] = required_success_rate
        self._required_mutation_ratio: Final[float] = required_mutation_ratio

        self._buffer: collections.deque[_InvocationRecord] = collections.deque(maxlen=self._capacity)
        self._lock: threading.Lock = threading.Lock()

    def record_invocation(
        self,
        is_success: bool,
        is_destructive: bool = False,
        is_violation: bool = False,
    ) -> None:
        """Appends one telemetry record to the sliding window (O(1))."""
        record = _InvocationRecord(
            is_success=is_success,
            is_destructive=is_destructive,
            is_violation=is_violation,
            timestamp=time.time(),
        )
        with self._lock:
            self._buffer.append(record)

    def get_metrics(self) -> AutonomyMetrics:
        """Computes current sliding window metrics snapshot."""
        with self._lock:
            total = len(self._buffer)
            if total == 0:
                return AutonomyMetrics(
                    window_size=self._capacity,
                    total_invocations=0,
                    successful_invocations=0,
                    failed_invocations=0,
                    destructive_invocations=0,
                    security_violations=0,
                    success_rate=0.0,
                    destructive_ratio=0.0,
                )

            successes = sum(1 for r in self._buffer if r.is_success)
            fails = total - successes
            destructives = sum(1 for r in self._buffer if r.is_destructive)
            violations = sum(1 for r in self._buffer if r.is_violation)

            return AutonomyMetrics(
                window_size=self._capacity,
                total_invocations=total,
                successful_invocations=successes,
                failed_invocations=fails,
                destructive_invocations=destructives,
                security_violations=violations,
                success_rate=round(successes / total, 4),
                destructive_ratio=round(destructives / total, 4),
            )

    def evaluate_promotion(self, current_level: AutonomyLevel) -> AutonomyPromotionResult:
        """Evaluates whether current sliding telemetry qualifies for level escalation."""
        metrics = self.get_metrics()

        # Rule 1: Zero tolerance on security policy violations
        if metrics.security_violations > 0:
            return AutonomyPromotionResult(
                eligible=False,
                current_level=current_level,
                recommended_level=None,
                reason=f"Security violations detected ({metrics.security_violations}); promotion strictly blocked",
                metrics=metrics,
            )

        # Rule 2: Cold-start check: insufficient samples
        if metrics.total_invocations < self._min_samples:
            return AutonomyPromotionResult(
                eligible=False,
                current_level=current_level,
                recommended_level=None,
                reason=f"Insufficient sample window ({metrics.total_invocations}/{self._min_samples})",
                metrics=metrics,
            )

        # Rule 3: Success rate threshold
        if metrics.success_rate < self._required_success_rate:
            return AutonomyPromotionResult(
                eligible=False,
                current_level=current_level,
                recommended_level=None,
                reason=(
                    f"Success rate {metrics.success_rate * 100:.1f}% below required "
                    f"{self._required_success_rate * 100:.1f}%"
                ),
                metrics=metrics,
            )

        # Rule 4: Goodhart's law defense: mutation action ratio
        if metrics.destructive_ratio < self._required_mutation_ratio:
            return AutonomyPromotionResult(
                eligible=False,
                current_level=current_level,
                recommended_level=None,
                reason=(
                    f"Mutation/write ratio {metrics.destructive_ratio * 100:.1f}% below required "
                    f"{self._required_mutation_ratio * 100:.1f}% (read-only grinding rejected)"
                ),
                metrics=metrics,
            )

        # Determine target next level
        if current_level == AutonomyLevel.L1_ADVISOR:
            recommended = AutonomyLevel.L2_COLLABORATOR
        elif current_level == AutonomyLevel.L2_COLLABORATOR or current_level == AutonomyLevel.L3_SUPERVISOR:
            recommended = AutonomyLevel.L4_CONDITIONAL
        else:
            return AutonomyPromotionResult(
                eligible=False,
                current_level=current_level,
                recommended_level=None,
                reason="Current level is already at or above L4 conditional autonomy",
                metrics=metrics,
            )

        return AutonomyPromotionResult(
            eligible=True,
            current_level=current_level,
            recommended_level=recommended,
            reason=f"Telemetry verified: {metrics.success_rate * 100:.1f}% success over {metrics.total_invocations} operations",
            metrics=metrics,
        )

    def reset(self) -> None:
        """Clears buffer (e.g. on new session or manual reset)."""
        with self._lock:
            self._buffer.clear()
