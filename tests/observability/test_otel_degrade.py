"""
[INPUT]:
- myrm_agent_harness.observability.otel_degrade::*

[OUTPUT]:
- Pytest verification for OpenTelemetry missing graceful degrade, No-Op fallbacks, and zero hard-dependency guarantees.

[POS]:
tests/observability/test_otel_degrade.py — OpenTelemetry 缺失时优雅降级（可观测探针零硬依赖）单元测试。
"""

import os
import pytest

from myrm_agent_harness.observability.otel_degrade import (
    GracefulOtelRuntime,
    NoOpCounter,
    NoOpMeter,
    NoOpSpan,
    NoOpTracer,
    OtelDegradeStatus,
    OtelPostureState,
)


def test_otel_degrade_when_dependency_missing() -> None:
    runtime = GracefulOtelRuntime()
    # 模拟环境未安装 opentelemetry 库
    runtime.simulate_missing_dependency(True)

    assert runtime.is_installed() is False
    status = runtime.probe_status()
    assert status.state == OtelPostureState.DEGRADED_NO_OP
    assert status.is_otel_installed is False
    assert "Dependency 'opentelemetry' is missing" in (status.degrade_reason or "")

    # 1. 获取 Tracer 并验证 NoOpTracer
    tracer = runtime.get_tracer("test.agent.loop")
    assert isinstance(tracer, NoOpTracer)

    # 2. 验证上下文管理器与 Span API 完备性，主业务流程零阻断且正常返回结果
    execution_result = 0
    with tracer.start_as_current_span("synthesize_plan") as span:
        assert isinstance(span, NoOpSpan)
        span.set_attribute("plan.id", "plan_001")
        span.set_attribute("plan.steps", 4)
        span.set_attributes({"model": "claude-3-7-sonnet", "temperature": 0.2})
        span.add_event("planning_started", {"timestamp": 123456})
        execution_result = 42

    assert execution_result == 42
    # 验证 Span 拦截计数
    updated_status = runtime.probe_status()
    assert updated_status.intercepted_spans_count == 1

    # 3. 验证异常透传铁律：探针必须忠实向上抛出业务异常，不得吞没业务错误
    with pytest.raises(ValueError, match="business failure"):
        with tracer.start_as_current_span("dangerous_tool") as span:
            span.record_exception(ValueError("business failure"))
            raise ValueError("business failure")

    # 4. 验证指标 Meter 与 Counter 降级
    meter = runtime.get_meter("test.agent.meter")
    assert isinstance(meter, NoOpMeter)
    counter = meter.create_counter("tokens_total")
    assert isinstance(counter, NoOpCounter)

    counter.add(15, {"kind": "prompt"})
    counter.add(25, {"kind": "completion"})

    final_status = runtime.probe_status()
    assert final_status.intercepted_spans_count == 2
    assert final_status.intercepted_metrics_count == 2


def test_otel_disabled_env_and_stats_reset() -> None:
    runtime = GracefulOtelRuntime()
    runtime.simulate_missing_dependency(False)

    # 设置禁用环境变量
    os.environ["MYRM_DISABLE_OTEL"] = "1"
    try:
        status = runtime.probe_status()
        assert status.state == OtelPostureState.DISABLED
        assert "Disabled via MYRM_DISABLE_OTEL" in (status.degrade_reason or "")
    finally:
        os.environ.pop("MYRM_DISABLE_OTEL", None)

    # 验证重置统计
    runtime.reset_stats()
    fresh_status = runtime.probe_status()
    assert fresh_status.intercepted_spans_count == 0
    assert fresh_status.intercepted_metrics_count == 0
