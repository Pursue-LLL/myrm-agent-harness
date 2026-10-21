"""[INPUT] Dynamic hardware metric readings and circuit breaker configuration adjustments.
[OUTPUT] Thread-safe three-tier runaway circuit breaker evaluating hardware resource violations.
[POS] myrm_agent_harness.observability.sandbox_hardware_telemetry.circuit_breaker

Three-tier laddered circuit breaker protecting local/cloud sandboxes against runaway loops:
- Level 1 (Warning >=80%): Alerts developer of spike.
- Level 2 (Suspended >=90%): Suspends task process group awaiting confirmation.
- Level 3 (Tripped >=95%): Hard termination, zombie cleanup, and crash incident logging.
"""

from collections import deque
import threading
import time

from .models import (
    CircuitBreakerConfig,
    CircuitBreakerEvaluation,
    CircuitBreakerLevel,
    HardwareMetricSample,
    HardwareTelemetrySnapshot,
)


class SandboxHardwareCircuitBreaker:
    """Thread-safe state machine evaluating sandbox hardware consumption against 3-tier thresholds."""

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self._lock = threading.Lock()
        self._config = config or CircuitBreakerConfig()
        self._current_level = CircuitBreakerLevel.NORMAL
        self._consecutive_violations = 0
        self._latest_sample: HardwareMetricSample | None = None
        self._incident_history: deque[CircuitBreakerEvaluation] = deque(maxlen=50)

    @property
    def config(self) -> CircuitBreakerConfig:
        with self._lock:
            return self._config

    def update_config(self, new_config: CircuitBreakerConfig) -> None:
        """Update circuit breaker operational thresholds and limits."""
        with self._lock:
            self._config = new_config

    def record_metric_sample(self, sample: HardwareMetricSample) -> CircuitBreakerEvaluation:
        """Ingest a new hardware usage reading and trigger three-tier safety evaluation."""
        with self._lock:
            self._latest_sample = sample
            cfg = self._config

            # Tier 3 (TRIPPED): 95% CPU or 95% Memory
            if sample.cpu_percent >= cfg.trip_cpu_threshold or sample.memory_percent >= cfg.trip_mem_threshold:
                self._consecutive_violations += 1
                trig_metric = "CPU" if sample.cpu_percent >= cfg.trip_cpu_threshold else "Memory"
                curr_val = sample.cpu_percent if trig_metric == "CPU" else sample.memory_percent
                th_val = cfg.trip_cpu_threshold if trig_metric == "CPU" else cfg.trip_mem_threshold

                if self._consecutive_violations >= cfg.max_consecutive_violations:
                    self._current_level = CircuitBreakerLevel.TRIPPED
                    action_desc = (
                        f"硬熔断已触发: {trig_metric} 持续超标 ({curr_val:.1f}% >= {th_val:.1f}%), "
                        "已物理终止失控进程组并回收句柄"
                    )
                else:
                    self._current_level = CircuitBreakerLevel.SUSPENDED
                    action_desc = (
                        f"超标预警递增 ({self._consecutive_violations}/{cfg.max_consecutive_violations}): "
                        f"{trig_metric} 极高消耗 ({curr_val:.1f}% >= {th_val:.1f}%)"
                    )

            # Tier 2 (SUSPENDED): 90% CPU or 90% Memory
            elif sample.cpu_percent >= cfg.suspend_cpu_threshold or sample.memory_percent >= cfg.suspend_mem_threshold:
                self._consecutive_violations = 0
                self._current_level = CircuitBreakerLevel.SUSPENDED
                trig_metric = "CPU" if sample.cpu_percent >= cfg.suspend_cpu_threshold else "Memory"
                curr_val = sample.cpu_percent if trig_metric == "CPU" else sample.memory_percent
                th_val = cfg.suspend_cpu_threshold if trig_metric == "CPU" else cfg.suspend_mem_threshold
                action_desc = (
                    f"橙色挂起保护已触发: {trig_metric} 资源占用高企 ({curr_val:.1f}% >= {th_val:.1f}%), "
                    "已自动挂起执行并等待用户介入"
                )

            # Tier 1 (WARNING): 80% CPU or 80% Memory
            elif sample.cpu_percent >= cfg.warning_cpu_threshold or sample.memory_percent >= cfg.warning_mem_threshold:
                self._consecutive_violations = 0
                self._current_level = CircuitBreakerLevel.WARNING
                trig_metric = "CPU" if sample.cpu_percent >= cfg.warning_cpu_threshold else "Memory"
                curr_val = sample.cpu_percent if trig_metric == "CPU" else sample.memory_percent
                th_val = cfg.warning_cpu_threshold if trig_metric == "CPU" else cfg.warning_mem_threshold
                action_desc = (
                    f"黄色预警已触发: {trig_metric} 出现资源激增峰值 ({curr_val:.1f}% >= {th_val:.1f}%), "
                    "已向前端推送资源消耗提示"
                )

            # Normal: <80% usage
            else:
                self._consecutive_violations = 0
                self._current_level = CircuitBreakerLevel.NORMAL
                trig_metric = "none"
                curr_val = max(sample.cpu_percent, sample.memory_percent)
                th_val = cfg.warning_cpu_threshold
                action_desc = "硬件各项水位正常放行，无失控死循环隐患"

            eval_result = CircuitBreakerEvaluation(
                level=self._current_level,
                triggered_metric=trig_metric,
                current_value=curr_val,
                threshold_value=th_val,
                action_description=action_desc,
                sample=sample,
                evaluated_at_ms=int(time.time() * 1000),
            )

            if self._current_level != CircuitBreakerLevel.NORMAL:
                self._incident_history.append(eval_result)

            return eval_result

    def get_snapshot(self) -> HardwareTelemetrySnapshot:
        """Capture atomic telemetry state snapshot for observability dashboards."""
        with self._lock:
            return HardwareTelemetrySnapshot(
                latest_sample=self._latest_sample,
                current_level=self._current_level,
                config=self._config,
                consecutive_violations=self._consecutive_violations,
                incident_history=tuple(self._incident_history),
                generated_at_ms=int(time.time() * 1000),
            )

    def reset(self) -> None:
        """Reset circuit breaker state to NORMAL and clear historical violation logs."""
        with self._lock:
            self._current_level = CircuitBreakerLevel.NORMAL
            self._consecutive_violations = 0
            self._incident_history.clear()


# Global thread-safe singleton
_default_breaker: SandboxHardwareCircuitBreaker | None = None
_breaker_lock = threading.Lock()


def get_default_hardware_circuit_breaker() -> SandboxHardwareCircuitBreaker:
    """Retrieve or initialize the global SandboxHardwareCircuitBreaker instance."""
    global _default_breaker
    if _default_breaker is None:
        with _breaker_lock:
            if _default_breaker is None:
                _default_breaker = SandboxHardwareCircuitBreaker()
    return _default_breaker
