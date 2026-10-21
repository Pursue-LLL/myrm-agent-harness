"""
[INPUT]: Memory operation samples, recall phases, and backend labels.
[OUTPUT]: MemoryBackendMetricsRecorder aggregating P50/P95 latencies, success rates, and degradation counts per backend.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/memory_backend_metrics/recorder.py
"""

import threading
import time
from typing import Dict, List, Optional
from uuid import uuid4

from .models import (
    MemoryBackendKind,
    MemoryBackendMetricsReport,
    MemoryBackendPerformanceStats,
    MemoryOperationMetricSample,
    MemoryOperationType,
    RecallPhaseType,
)


class MemoryBackendMetricsRecorder:
    """Thread-safe recorder and aggregator for opt-in memories_backend operation and recall-phase metrics."""

    def __init__(self, opt_in_enabled: bool = True) -> None:
        self._lock = threading.Lock()
        self._opt_in_enabled = opt_in_enabled
        self._samples: List[MemoryOperationMetricSample] = []

    def configure(self, opt_in_enabled: bool) -> None:
        """Dynamically toggle the opt-in memories_backend high-cardinality dimension."""
        with self._lock:
            self._opt_in_enabled = opt_in_enabled

    def record_sample(
        self,
        backend: MemoryBackendKind,
        operation: MemoryOperationType,
        duration_ms: float,
        phase: RecallPhaseType = RecallPhaseType.NONE,
        success: bool = True,
        degraded: bool = False,
        timestamp_ms: Optional[int] = None,
    ) -> Optional[MemoryOperationMetricSample]:
        """Record an operation metric sample with memories_backend label if opt-in is enabled."""
        with self._lock:
            if not self._opt_in_enabled:
                return None

            sample = MemoryOperationMetricSample(
                sample_id=f"mem-{uuid4().hex[:12]}",
                backend=backend,
                operation=operation,
                phase=phase,
                duration_ms=max(0.0, float(duration_ms)),
                success=success,
                degraded=degraded,
                timestamp_ms=timestamp_ms if timestamp_ms is not None else int(time.time() * 1000),
            )
            self._samples.append(sample)
            return sample

    def get_report(self) -> MemoryBackendMetricsReport:
        """Generate comprehensive performance comparison across memory backends and recall phases."""
        with self._lock:
            opt_in = self._opt_in_enabled
            samples = list(self._samples)

        # Group by (backend, operation, phase)
        grouped: Dict[tuple[MemoryBackendKind, MemoryOperationType, RecallPhaseType], List[MemoryOperationMetricSample]] = {}
        for s in samples:
            key = (s.backend, s.operation, s.phase)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(s)

        stats_list: List[MemoryBackendPerformanceStats] = []
        for (b, op, ph), group in sorted(grouped.items(), key=lambda x: (x[0][0].value, x[0][1].value, x[0][2].value)):
            total_ops = len(group)
            success_count = sum(1 for item in group if item.success)
            degraded_count = sum(1 for item in group if item.degraded)
            success_rate = (success_count / total_ops) if total_ops > 0 else 1.0

            durations = sorted([item.duration_ms for item in group])
            avg_duration = sum(durations) / total_ops if total_ops > 0 else 0.0

            # Calculate p50 and p95
            p50_idx = int(0.50 * total_ops)
            p95_idx = min(int(0.95 * total_ops), total_ops - 1)
            p50_val = durations[p50_idx] if total_ops > 0 else 0.0
            p95_val = durations[p95_idx] if total_ops > 0 else 0.0

            stats_list.append(
                MemoryBackendPerformanceStats(
                    backend=b,
                    operation=op,
                    phase=ph,
                    total_operations=total_ops,
                    success_count=success_count,
                    success_rate=round(success_rate, 4),
                    degraded_count=degraded_count,
                    avg_duration_ms=round(avg_duration, 2),
                    p50_duration_ms=round(p50_val, 2),
                    p95_duration_ms=round(p95_val, 2),
                )
            )

        return MemoryBackendMetricsReport(
            opt_in_enabled=opt_in,
            total_samples=len(samples),
            backend_stats=stats_list,
            timestamp_ms=int(time.time() * 1000),
        )

    def reset(self) -> None:
        """Clear recorded samples for isolated testing."""
        with self._lock:
            self._samples.clear()
