"""
[INPUT]: Tracer/Meter creation requests, span lifecycle invocations, and metric recording calls.
[OUTPUT]: Robust NoOp fallback primitives and GracefulOtelRuntime providing zero hard-dependency guarantees.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/otel_degrade/runtime.py
"""

from datetime import datetime, timezone
import importlib.util
import os
import threading
from typing import Any, Dict, Optional, Union

from .models import OtelDegradeStatus, OtelPostureState


class NoOpSpan:
    """零开销、零副作用的虚空 Span（符合 OpenTelemetry TraceSpan API 契约）"""

    def __init__(self, name: str, runtime: "GracefulOtelRuntime") -> None:
        self.name = name
        self._runtime = runtime

    def __enter__(self) -> "NoOpSpan":
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[object],
    ) -> None:
        # 绝不吞掉异常，保持用户业务代码异常抛出行为原样不变
        return None

    def set_attribute(self, key: str, value: Union[str, int, float, bool]) -> "NoOpSpan":
        return self

    def set_attributes(
        self, attributes: Dict[str, Union[str, int, float, bool]]
    ) -> "NoOpSpan":
        return self

    def set_status(self, status: object, description: Optional[str] = None) -> "NoOpSpan":
        return self

    def record_exception(self, exception: BaseException) -> "NoOpSpan":
        return self

    def add_event(
        self,
        name: str,
        attributes: Optional[Dict[str, Union[str, int, float, bool]]] = None,
    ) -> "NoOpSpan":
        return self

    def end(self) -> None:
        pass


class NoOpTracer:
    """零硬依赖的虚空 Tracer，确保在缺失 opentelemetry-api 时主业务流程平滑推进"""

    def __init__(self, name: str, runtime: "GracefulOtelRuntime") -> None:
        self.name = name
        self._runtime = runtime

    def start_span(self, name: str, **kwargs: object) -> NoOpSpan:
        self._runtime.increment_intercepted_spans()
        return NoOpSpan(name=name, runtime=self._runtime)

    def start_as_current_span(self, name: str, **kwargs: object) -> NoOpSpan:
        self._runtime.increment_intercepted_spans()
        return NoOpSpan(name=name, runtime=self._runtime)


class NoOpCounter:
    """零开销指标计数器"""

    def __init__(self, name: str, runtime: "GracefulOtelRuntime") -> None:
        self.name = name
        self._runtime = runtime

    def add(
        self,
        amount: Union[int, float],
        attributes: Optional[Dict[str, Union[str, int, float, bool]]] = None,
    ) -> None:
        self._runtime.increment_intercepted_metrics()


class NoOpMeter:
    """零硬依赖的虚空 Meter，确保指标上报代码零异常穿透"""

    def __init__(self, name: str, runtime: "GracefulOtelRuntime") -> None:
        self.name = name
        self._runtime = runtime

    def create_counter(self, name: str, **kwargs: object) -> NoOpCounter:
        return NoOpCounter(name=name, runtime=self._runtime)

    def create_histogram(self, name: str, **kwargs: object) -> NoOpCounter:
        return NoOpCounter(name=name, runtime=self._runtime)


class GracefulOtelRuntime:
    """OpenTelemetry 优雅降级运行时（零硬依赖守护者）"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._simulate_missing: bool = False
        self._intercepted_spans: int = 0
        self._intercepted_metrics: int = 0

    def increment_intercepted_spans(self) -> None:
        with self._lock:
            self._intercepted_spans += 1

    def increment_intercepted_metrics(self) -> None:
        with self._lock:
            self._intercepted_metrics += 1

    def simulate_missing_dependency(self, simulate: bool) -> None:
        """测试期/故障注入辅助：模拟未安装 opentelemetry 库"""
        with self._lock:
            self._simulate_missing = simulate

    def is_installed(self) -> bool:
        """检查环境中是否真实安装了 opentelemetry-api 模块"""
        if self._simulate_missing:
            return False
        return importlib.util.find_spec("opentelemetry") is not None

    def get_tracer(self, name: str) -> object:
        """安全获取 Tracer：安装则返回官方 Tracer，缺失则返回 NoOpTracer 优雅降级"""
        if self.is_installed():
            try:
                from opentelemetry import trace  # type: ignore

                return trace.get_tracer(name)
            except Exception:
                pass
        return NoOpTracer(name=name, runtime=self)

    def get_meter(self, name: str) -> object:
        """安全获取 Meter：安装则返回官方 Meter，缺失则返回 NoOpMeter 优雅降级"""
        if self.is_installed():
            try:
                from opentelemetry import metrics  # type: ignore

                return metrics.get_meter(name)
            except Exception:
                pass
        return NoOpMeter(name=name, runtime=self)

    def probe_status(self) -> OtelDegradeStatus:
        """探测当前可观测性探针的运行姿态与降级状态"""
        with self._lock:
            now_iso = datetime.now(timezone.utc).isoformat()
            installed = self.is_installed()

            # 检查环境变量是否明确禁用
            disabled_env = os.environ.get("MYRM_DISABLE_OTEL", "").lower() in (
                "1",
                "true",
                "yes",
            )
            if disabled_env:
                state = OtelPostureState.DISABLED
                reason = "Disabled via MYRM_DISABLE_OTEL environment variable"
            elif not installed:
                state = OtelPostureState.DEGRADED_NO_OP
                reason = (
                    "Dependency 'opentelemetry' is missing; gracefully degraded to No-Op"
                )
            else:
                state = OtelPostureState.ACTIVE
                reason = None

            return OtelDegradeStatus(
                state=state,
                is_otel_installed=installed,
                degrade_reason=reason,
                intercepted_spans_count=self._intercepted_spans,
                intercepted_metrics_count=self._intercepted_metrics,
                last_probe_time=now_iso,
            )

    def reset_stats(self) -> None:
        """重置统计计数（用于测试隔离）"""
        with self._lock:
            self._intercepted_spans = 0
            self._intercepted_metrics = 0
            self._simulate_missing = False
