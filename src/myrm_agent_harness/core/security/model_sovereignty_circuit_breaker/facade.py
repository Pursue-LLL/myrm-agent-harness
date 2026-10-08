"""
[POS] src/myrm_agent_harness/core/security/model_sovereignty_circuit_breaker/facade.py
[INPUT] typing, .types, .degradation_fingerprint_probe, .circuit_breaker_router, .sovereign_governance_enclave
[OUTPUT] ModelSovereigntyCircuitBreakerSuite

Unified facade for Model Degradation Circuit Breaker & Sovereign Governance Enclave.
Coordinates stealth model swap fingerprinting, automated fallback routing,
and full-stack self-hosted digital sovereignty posture verification.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .circuit_breaker_router import ModelDegradationCircuitBreaker
from .degradation_fingerprint_probe import ModelDegradationFingerprintProbe
from .sovereign_governance_enclave import SovereignGovernanceEnclave
from .types import (
    CircuitState,
    DegradationCircuitBreakerMetrics,
    MeshNodeSpec,
    ModelFingerprintReport,
    ModelInferenceProbeInput,
    SovereignEnclavePosture,
)

logger = logging.getLogger(__name__)


class ModelSovereigntyCircuitBreakerSuite:
    """Unified security suite safeguarding against cloud model degradation and ensuring digital sovereignty."""

    def __init__(
        self,
        probe: ModelDegradationFingerprintProbe | None = None,
        circuit_breaker: ModelDegradationCircuitBreaker | None = None,
        enclave: SovereignGovernanceEnclave | None = None,
    ) -> None:
        self._probe = probe or ModelDegradationFingerprintProbe()
        self._circuit_breaker = circuit_breaker or ModelDegradationCircuitBreaker()
        self._enclave = enclave or SovereignGovernanceEnclave()
        self._metrics = DegradationCircuitBreakerMetrics()

    @property
    def metrics(self) -> DegradationCircuitBreakerMetrics:
        """Retrieve cumulative metrics for model degradation and sovereignty defense."""
        return self._metrics

    def inspect_telemetry(
        self,
        telemetry: ModelInferenceProbeInput,
    ) -> tuple[ModelFingerprintReport, CircuitState, bool]:
        """Analyze inference telemetry and update circuit state machine.

        Returns (report, new_circuit_state, did_circuit_trip).
        """
        self._metrics.fingerprint_inspections_total += 1
        report = self._probe.inspect_inference_telemetry(telemetry)

        if report.is_silent_swap_suspected:
            self._metrics.silent_swaps_detected_total += 1

        state, did_trip = self._circuit_breaker.record_inspection_report(report)
        if did_trip:
            self._metrics.circuit_trips_total += 1
        elif state == CircuitState.CLOSED and self._circuit_breaker.get_circuit_state(telemetry.provider_id) == CircuitState.HALF_OPEN:
            self._metrics.circuit_recoveries_total += 1

        return report, state, did_trip

    def route_request(self, provider_id: str, fallback_target: str) -> tuple[str, bool]:
        """Determine endpoint routing based on degradation circuit state."""
        target, is_fallback = self._circuit_breaker.route_request(provider_id, fallback_target)
        if is_fallback:
            self._metrics.fallback_reroutes_total += 1
        return target, is_fallback

    def get_circuit_state(self, provider_id: str) -> CircuitState:
        """Query current circuit state for a provider."""
        return self._circuit_breaker.get_circuit_state(provider_id)

    def reset_circuit(self, provider_id: str) -> None:
        """Manually reset a tripped circuit breaker to healthy CLOSED."""
        self._circuit_breaker.reset_circuit(provider_id)

    def audit_sovereignty_posture(
        self,
        is_data_self_hosted: bool,
        is_model_self_hosted: bool,
        is_tool_sandbox_isolated: bool,
        active_storage_mode: str = "sqlite_local_volume",
        active_model_endpoint: str = "http://localhost:11434",
    ) -> SovereignEnclavePosture:
        """Audit data, model, and tool sovereignty, computing autonomy health score."""
        self._metrics.sovereign_audits_total += 1
        return self._enclave.audit_sovereignty_posture(
            is_data_self_hosted=is_data_self_hosted,
            is_model_self_hosted=is_model_self_hosted,
            is_tool_sandbox_isolated=is_tool_sandbox_isolated,
            active_storage_mode=active_storage_mode,
            active_model_endpoint=active_model_endpoint,
        )

    def register_mesh_node(
        self,
        node_id: str,
        hostname: str,
        node_type: str,
        capacity_weight: int = 10,
    ) -> MeshNodeSpec:
        """Register compute node into heterogeneous mesh."""
        return self._enclave.register_mesh_node(
            node_id=node_id,
            hostname=hostname,
            node_type=node_type,
            capacity_weight=capacity_weight,
        )

    def record_node_heartbeat(self, node_id: str) -> bool:
        """Record heartbeat for mesh node."""
        return self._enclave.record_node_heartbeat(node_id)

    def list_healthy_nodes(self) -> list[MeshNodeSpec]:
        """List active nodes in local mesh."""
        return self._enclave.list_healthy_nodes()

    def get_best_compute_node(self, preferred_type: str = "gpu_worker") -> MeshNodeSpec | None:
        """Find best available compute node."""
        return self._enclave.get_best_compute_node(preferred_type)
