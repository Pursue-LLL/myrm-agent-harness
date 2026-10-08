"""
[POS] src/myrm_agent_harness/core/security/model_sovereignty_circuit_breaker/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] CircuitState, DegradationSeverity, ModelInferenceProbeInput, ModelFingerprintReport, SovereignEnclavePosture, MeshNodeSpec, DegradationCircuitBreakerMetrics

Data structures and domain types for Model Degradation Circuit Breaker & Sovereign Governance Enclave.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CircuitState(StrEnum):
    """Circuit breaker operational state."""

    CLOSED = "CLOSED"  # Healthy, normal traffic
    OPEN = "OPEN"      # Tripped due to degradation, rerouting to fallback
    HALF_OPEN = "HALF_OPEN"  # Testing canary probe for recovery


class DegradationSeverity(StrEnum):
    """Detected degradation or model swap severity level."""

    NORMAL = "NORMAL"
    SLIGHT_DEVIATION = "SLIGHT_DEVIATION"
    SEVERE_DOWNGRADE = "SEVERE_DOWNGRADE"
    TOTAL_OUTAGE = "TOTAL_OUTAGE"


@dataclass(frozen=True)
class ModelInferenceProbeInput:
    """Telemetry captured from a model inference response for degradation analysis."""

    provider_id: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    output_text: str
    expected_tool_call: bool = False
    valid_tool_call_produced: bool = True
    refusal_detected: bool = False


@dataclass(frozen=True)
class ModelFingerprintReport:
    """Evaluation result of model output fingerprint against baseline."""

    provider_id: str
    model_name: str
    deviation_score: float  # 0.0 (identical) to 1.0 (completely divergent)
    severity: DegradationSeverity
    is_silent_swap_suspected: bool
    diagnostic_reason: str
    timestamp: float


@dataclass(frozen=True)
class SovereignEnclavePosture:
    """Audit of data, model, and toolchain self-hosted digital sovereignty."""

    enclave_id: str
    is_data_self_hosted: bool
    is_model_self_hosted: bool
    is_tool_sandbox_isolated: bool
    sovereignty_score: int  # 0 to 100
    active_storage_mode: str
    active_model_endpoint: str
    timestamp: float


@dataclass(frozen=True)
class MeshNodeSpec:
    """Registered compute node in heterogeneous local mesh."""

    node_id: str
    hostname: str
    node_type: str  # "workstation", "gpu_worker", "edge_node"
    is_healthy: bool
    capacity_weight: int
    last_heartbeat: float


@dataclass
class DegradationCircuitBreakerMetrics:
    """Cumulative metrics tracking model degradation detections and circuit trips."""

    fingerprint_inspections_total: int = 0
    silent_swaps_detected_total: int = 0
    circuit_trips_total: int = 0
    circuit_recoveries_total: int = 0
    fallback_reroutes_total: int = 0
    sovereign_audits_total: int = 0
