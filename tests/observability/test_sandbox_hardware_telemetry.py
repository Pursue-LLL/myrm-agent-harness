"""[INPUT] Dynamic sandbox hardware readings and circuit breaker threshold adjustments.
[OUTPUT] Unit tests verifying three-tier laddered runaway circuit breaker evaluation and recovery.
[POS] myrm-agent-harness/tests/observability/test_sandbox_hardware_telemetry.py
"""

from myrm_agent_harness.observability.sandbox_hardware_telemetry import (
    CircuitBreakerConfig,
    CircuitBreakerEvaluation,
    CircuitBreakerLevel,
    HardwareMetricSample,
    SandboxHardwareCircuitBreaker,
)


def _create_sample(cpu: float = 30.0, mem_pct: float = 40.0) -> HardwareMetricSample:
    return HardwareMetricSample(
        cpu_percent=cpu,
        memory_used_bytes=4294967296,
        memory_total_bytes=8589934592,
        memory_percent=mem_pct,
        disk_used_bytes=21474836480,
        disk_total_bytes=107374182400,
        disk_percent=20.0,
        network_bytes_sent=1024,
        network_bytes_recv=2048,
    )


def test_normal_hardware_telemetry_flow() -> None:
    """Verifies that normal load results in NORMAL level without incidents."""
    breaker = SandboxHardwareCircuitBreaker()
    sample = _create_sample(cpu=35.0, mem_pct=45.0)
    ev: CircuitBreakerEvaluation = breaker.record_metric_sample(sample)

    assert ev.level == CircuitBreakerLevel.NORMAL
    assert ev.triggered_metric == "none"
    assert "正常放行" in ev.action_description

    snapshot = breaker.get_snapshot()
    assert snapshot.current_level == CircuitBreakerLevel.NORMAL
    assert snapshot.consecutive_violations == 0
    assert len(snapshot.incident_history) == 0


def test_level_1_warning() -> None:
    """Verifies that CPU >= 80% triggers WARNING level."""
    breaker = SandboxHardwareCircuitBreaker()
    sample = _create_sample(cpu=82.5, mem_pct=50.0)
    ev = breaker.record_metric_sample(sample)

    assert ev.level == CircuitBreakerLevel.WARNING
    assert ev.triggered_metric == "CPU"
    assert ev.current_value == 82.5
    assert "黄色预警已触发" in ev.action_description

    snapshot = breaker.get_snapshot()
    assert snapshot.current_level == CircuitBreakerLevel.WARNING
    assert len(snapshot.incident_history) == 1


def test_level_2_suspended() -> None:
    """Verifies that Memory >= 90% triggers SUSPENDED protection level."""
    breaker = SandboxHardwareCircuitBreaker()
    sample = _create_sample(cpu=40.0, mem_pct=91.0)
    ev = breaker.record_metric_sample(sample)

    assert ev.level == CircuitBreakerLevel.SUSPENDED
    assert ev.triggered_metric == "Memory"
    assert ev.current_value == 91.0
    assert "橙色挂起保护已触发" in ev.action_description

    snapshot = breaker.get_snapshot()
    assert snapshot.current_level == CircuitBreakerLevel.SUSPENDED


def test_level_3_tripped_after_consecutive_violations() -> None:
    """Verifies that 3 consecutive Tier 3 violations escalate to TRIPPED."""
    breaker = SandboxHardwareCircuitBreaker(
        config=CircuitBreakerConfig(max_consecutive_violations=3, trip_cpu_threshold=95.0)
    )

    # 1st violation -> SUSPENDED
    ev1 = breaker.record_metric_sample(_create_sample(cpu=96.0))
    assert ev1.level == CircuitBreakerLevel.SUSPENDED

    # 2nd violation -> SUSPENDED
    ev2 = breaker.record_metric_sample(_create_sample(cpu=97.0))
    assert ev2.level == CircuitBreakerLevel.SUSPENDED

    # 3rd violation -> TRIPPED
    ev3 = breaker.record_metric_sample(_create_sample(cpu=98.0))
    assert ev3.level == CircuitBreakerLevel.TRIPPED
    assert "硬熔断已触发" in ev3.action_description

    snapshot = breaker.get_snapshot()
    assert snapshot.current_level == CircuitBreakerLevel.TRIPPED
    assert snapshot.consecutive_violations == 3


def test_config_update_and_reset() -> None:
    """Verifies custom threshold configuration and circuit reset."""
    breaker = SandboxHardwareCircuitBreaker()
    custom_cfg = CircuitBreakerConfig(warning_cpu_threshold=70.0, max_consecutive_violations=2)
    breaker.update_config(custom_cfg)

    assert breaker.config.warning_cpu_threshold == 70.0

    # 72% CPU should now trigger WARNING under 70% threshold
    ev = breaker.record_metric_sample(_create_sample(cpu=72.0))
    assert ev.level == CircuitBreakerLevel.WARNING

    # Reset
    breaker.reset()
    snap = breaker.get_snapshot()
    assert snap.current_level == CircuitBreakerLevel.NORMAL
    assert len(snap.incident_history) == 0
