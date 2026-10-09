# [INPUT]: AnomalyGuardStatus, CacheMissAnomalyReport, COLD_MISS_TOKEN_THRESHOLD, MAX_CONSECUTIVE_COLD_MISSES from roll_forward_types
# [OUTPUT]: CacheMissAnomalyGuard
# [POS]: myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.cache_miss_anomaly_guard
"""Anomaly guard and circuit-breaker fuse for consecutive prompt cache misses (Item 330).

Detects cache miss spikes during multi-round autonomous tool loops where
cache_control failed to roll forward, preventing runaway token bills.
"""

from __future__ import annotations

import threading
from typing import Final

from myrm_agent_harness.agent.context_management.prompt_cache_roll_forward.roll_forward_types import (
    COLD_MISS_TOKEN_THRESHOLD,
    MAX_CONSECUTIVE_COLD_MISSES,
    AnomalyGuardStatus,
    CacheMissAnomalyReport,
)


class CacheMissAnomalyGuard:
    """Fuse that halts autonomous loops if consecutive catastrophic cache misses occur."""

    def __init__(
        self,
        token_threshold: int = COLD_MISS_TOKEN_THRESHOLD,
        max_consecutive_misses: int = MAX_CONSECUTIVE_COLD_MISSES,
    ) -> None:
        self._lock = threading.RLock()
        self._token_threshold: Final[int] = token_threshold
        self._max_consecutive_misses: Final[int] = max_consecutive_misses
        self._consecutive_cold_misses: int = 0
        self._circuit_broken: bool = False
        self._last_report: CacheMissAnomalyReport | None = None

    @property
    def is_circuit_broken(self) -> bool:
        """True if the autonomous loop has been halted due to cache miss spike."""
        with self._lock:
            return self._circuit_broken

    @property
    def consecutive_cold_misses(self) -> int:
        """Current number of consecutive cold cache misses observed."""
        with self._lock:
            return self._consecutive_cold_misses

    def record_round_tokens(
        self,
        round_index: int,
        input_tokens: int,
        cache_read_tokens: int,
    ) -> CacheMissAnomalyReport:
        """Evaluate cache performance for a tool round and trip circuit if anomalous.

        Args:
            round_index: Sequential index of the tool round.
            input_tokens: Total prompt input tokens reported by provider.
            cache_read_tokens: Prompt tokens served from cache.

        Returns:
            CacheMissAnomalyReport detailing health status and verdict.
        """
        with self._lock:
            # Check if this round experienced a severe cold cache miss
            is_severe_miss = (cache_read_tokens == 0) and (input_tokens >= self._token_threshold)

            if is_severe_miss:
                self._consecutive_cold_misses += 1
            else:
                # Cache hit or below token threshold resets consecutive counter
                self._consecutive_cold_misses = 0
                if not self._circuit_broken:
                    report = CacheMissAnomalyReport(
                        status=AnomalyGuardStatus.NORMAL,
                        consecutive_cold_misses=0,
                        last_input_tokens=input_tokens,
                        last_cache_read_tokens=cache_read_tokens,
                        is_circuit_broken=False,
                        reason=f"Round {round_index} cache hit healthy ({cache_read_tokens}/{input_tokens} tokens)",
                        suggested_action="continue",
                    )
                    self._last_report = report
                    return report

            # Evaluate against threshold
            if self._consecutive_cold_misses >= self._max_consecutive_misses:
                self._circuit_broken = True
                report = CacheMissAnomalyReport(
                    status=AnomalyGuardStatus.FUSED_CIRCUIT_BROKEN,
                    consecutive_cold_misses=self._consecutive_cold_misses,
                    last_input_tokens=input_tokens,
                    last_cache_read_tokens=cache_read_tokens,
                    is_circuit_broken=True,
                    reason=(
                        f"CRITICAL: Consecutive catastrophic cache misses detected ({self._consecutive_cold_misses} rounds >= "
                        f"{self._max_consecutive_misses}) with input tokens {input_tokens} >= {self._token_threshold}. "
                        "Autonomous loop circuit breaker tripped to protect quota."
                    ),
                    suggested_action="halt_and_diagnose",
                )
                self._last_report = report
                return report

            if self._consecutive_cold_misses > 0:
                report = CacheMissAnomalyReport(
                    status=AnomalyGuardStatus.WARNING,
                    consecutive_cold_misses=self._consecutive_cold_misses,
                    last_input_tokens=input_tokens,
                    last_cache_read_tokens=cache_read_tokens,
                    is_circuit_broken=False,
                    reason=(
                        f"WARNING: Cold cache miss on round {round_index} ({input_tokens} input tokens without cache hit). "
                        "Monitoring next round."
                    ),
                    suggested_action="monitor_next_round",
                )
                self._last_report = report
                return report

            report = CacheMissAnomalyReport(
                status=AnomalyGuardStatus.NORMAL,
                consecutive_cold_misses=0,
                last_input_tokens=input_tokens,
                last_cache_read_tokens=cache_read_tokens,
                is_circuit_broken=False,
                reason="Normal cache operation",
                suggested_action="continue",
            )
            self._last_report = report
            return report

    def reset_fuse(self) -> None:
        """Manually reset the circuit breaker after user intervention or reconnection."""
        with self._lock:
            self._consecutive_cold_misses = 0
            self._circuit_broken = False
            self._last_report = None

    def get_last_report(self) -> CacheMissAnomalyReport | None:
        """Retrieve the most recent health report."""
        with self._lock:
            return self._last_report
