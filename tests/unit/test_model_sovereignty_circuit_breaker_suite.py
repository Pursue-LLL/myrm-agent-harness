"""
Unit tests for Model Sovereignty Circuit Breaker & Sovereign Governance Enclave Suite.
"""

from __future__ import annotations

import time

from myrm_agent_harness.core.security.model_sovereignty_circuit_breaker import (
    CircuitState,
    DegradationSeverity,
    ModelDegradationCircuitBreaker,
    ModelDegradationFingerprintProbe,
    ModelInferenceProbeInput,
    ModelSovereigntyCircuitBreakerSuite,
    SovereignGovernanceEnclave,
)


def test_degradation_fingerprint_probe_evaluations() -> None:
    probe = ModelDegradationFingerprintProbe(deviation_threshold=0.40)

    # 1. Normal healthy completion
    normal_input = ModelInferenceProbeInput(
        provider_id="cloud-llm-1",
        model_name="claude-3-opus",
        prompt_tokens=100,
        completion_tokens=250,
        latency_ms=850.0,
        output_text="Here is your analysis of the quarterly results...",
        expected_tool_call=False,
        valid_tool_call_produced=True,
        refusal_detected=False,
    )
    report_normal = probe.inspect_inference_telemetry(normal_input)
    assert report_normal.severity == DegradationSeverity.NORMAL
    assert not report_normal.is_silent_swap_suspected
    assert report_normal.deviation_score == 0.0

    # 2. Total outage (0 tokens empty output)
    outage_input = ModelInferenceProbeInput(
        provider_id="cloud-llm-1",
        model_name="claude-3-opus",
        prompt_tokens=100,
        completion_tokens=0,
        latency_ms=50.0,
        output_text="",
        expected_tool_call=False,
        valid_tool_call_produced=True,
    )
    report_outage = probe.inspect_inference_telemetry(outage_input)
    assert report_outage.severity == DegradationSeverity.TOTAL_OUTAGE
    assert report_outage.is_silent_swap_suspected
    assert report_outage.deviation_score == 1.0

    # 3. Tool call degradation
    tool_broken_input = ModelInferenceProbeInput(
        provider_id="cloud-llm-1",
        model_name="claude-3-opus",
        prompt_tokens=100,
        completion_tokens=50,
        latency_ms=300.0,
        output_text="I should use the tool now, but plain text instead.",
        expected_tool_call=True,
        valid_tool_call_produced=False,
    )
    report_tool = probe.inspect_inference_telemetry(tool_broken_input)
    assert report_tool.deviation_score >= 0.50
    assert report_tool.is_silent_swap_suspected

    # 4. Refusal and micro-completion
    refusal_input = ModelInferenceProbeInput(
        provider_id="cloud-llm-1",
        model_name="claude-3-opus",
        prompt_tokens=80,
        completion_tokens=4,
        latency_ms=120.0,
        output_text="No.",
        expected_tool_call=False,
        refusal_detected=True,
    )
    report_refusal = probe.inspect_inference_telemetry(refusal_input)
    # 0.35 (refusal) + 0.30 (short completion) = 0.65
    assert report_refusal.deviation_score >= 0.60
    assert report_refusal.is_silent_swap_suspected


def test_circuit_breaker_state_transitions() -> None:
    breaker = ModelDegradationCircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)

    # Initial state CLOSED
    assert breaker.get_circuit_state("provider-a") == CircuitState.CLOSED
    target, is_fallback = breaker.route_request("provider-a", "fallback-ollama")
    assert target == "provider-a"
    assert not is_fallback

    # Probe 1: severe downgrade failure
    probe = ModelDegradationFingerprintProbe()
    fail_telemetry = ModelInferenceProbeInput(
        provider_id="provider-a",
        model_name="test-model",
        prompt_tokens=100,
        completion_tokens=0,
        latency_ms=10.0,
        output_text="",
    )
    report_1 = probe.inspect_inference_telemetry(fail_telemetry)
    state, did_trip = breaker.record_inspection_report(report_1)
    assert state == CircuitState.CLOSED
    assert not did_trip

    # Probe 2: reaches threshold -> trips OPEN
    report_2 = probe.inspect_inference_telemetry(fail_telemetry)
    state, did_trip = breaker.record_inspection_report(report_2)
    assert state == CircuitState.OPEN
    assert did_trip

    # When OPEN, reroutes to fallback
    target, is_fallback = breaker.route_request("provider-a", "fallback-ollama")
    assert target == "fallback-ollama"
    assert is_fallback

    # Cooldown elapses -> transitions to HALF_OPEN
    time.sleep(0.12)
    assert breaker.get_circuit_state("provider-a") == CircuitState.HALF_OPEN

    # Passing probe in HALF_OPEN resets to CLOSED
    success_telemetry = ModelInferenceProbeInput(
        provider_id="provider-a",
        model_name="test-model",
        prompt_tokens=100,
        completion_tokens=100,
        latency_ms=400.0,
        output_text="Healthy output recovered.",
    )
    report_success = probe.inspect_inference_telemetry(success_telemetry)
    state, did_trip = breaker.record_inspection_report(report_success)
    assert state == CircuitState.CLOSED
    assert not did_trip

    # Reset test
    breaker.record_inspection_report(report_1)
    breaker.record_inspection_report(report_2)
    assert breaker.get_circuit_state("provider-a") == CircuitState.OPEN
    breaker.reset_circuit("provider-a")
    assert breaker.get_circuit_state("provider-a") == CircuitState.CLOSED


def test_sovereign_governance_enclave_and_mesh() -> None:
    enclave = SovereignGovernanceEnclave()

    # Full sovereignty (100)
    posture_full = enclave.audit_sovereignty_posture(
        is_data_self_hosted=True,
        is_model_self_hosted=True,
        is_tool_sandbox_isolated=True,
    )
    assert posture_full.sovereignty_score == 100

    # Partial sovereignty (data=35, model_api=10, sandbox=30 -> 75)
    posture_partial = enclave.audit_sovereignty_posture(
        is_data_self_hosted=True,
        is_model_self_hosted=False,
        is_tool_sandbox_isolated=True,
    )
    assert posture_partial.sovereignty_score == 75

    # Mesh Node Management
    node1 = enclave.register_mesh_node(
        node_id="node-mac-studio",
        hostname="studio.lan",
        node_type="gpu_worker",
        capacity_weight=30,
    )
    assert node1.is_healthy

    node2 = enclave.register_mesh_node(
        node_id="node-edge-pi",
        hostname="pi.lan",
        node_type="edge_node",
        capacity_weight=5,
    )
    assert node2.is_healthy

    healthy_nodes = enclave.list_healthy_nodes()
    assert len(healthy_nodes) == 2

    # Best compute node selection
    best_gpu = enclave.get_best_compute_node(preferred_type="gpu_worker")
    assert best_gpu is not None
    assert best_gpu.node_id == "node-mac-studio"

    # Heartbeat
    assert enclave.record_node_heartbeat("node-mac-studio")
    assert not enclave.record_node_heartbeat("non-existent-node")


def test_model_sovereignty_circuit_breaker_facade() -> None:
    suite = ModelSovereigntyCircuitBreakerSuite()

    # 1. Telemetry inspection & metrics
    telemetry = ModelInferenceProbeInput(
        provider_id="cloud-ai",
        model_name="llm-v1",
        prompt_tokens=50,
        completion_tokens=50,
        latency_ms=200.0,
        output_text="Valid completion",
    )
    report, state, did_trip = suite.inspect_telemetry(telemetry)
    assert report.provider_id == "cloud-ai"
    assert state == CircuitState.CLOSED
    assert not did_trip
    assert suite.metrics.fingerprint_inspections_total == 1

    # Route request
    target, is_fallback = suite.route_request("cloud-ai", "local-ollama")
    assert target == "cloud-ai"
    assert not is_fallback

    # 2. Sovereignty posture audit
    posture = suite.audit_sovereignty_posture(
        is_data_self_hosted=True,
        is_model_self_hosted=True,
        is_tool_sandbox_isolated=True,
    )
    assert posture.sovereignty_score == 100
    assert suite.metrics.sovereign_audits_total == 1

    # 3. Mesh management via facade
    node = suite.register_mesh_node("node-1", "host-1", "gpu_worker", 20)
    assert node.node_id == "node-1"
    assert len(suite.list_healthy_nodes()) == 1
    assert suite.get_best_compute_node() is not None
    assert suite.record_node_heartbeat("node-1")
