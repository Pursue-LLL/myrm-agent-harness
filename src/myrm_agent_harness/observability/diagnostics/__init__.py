"""Diagnostics module — framework-level self-inspection and health-check protocol.

[INPUT]
- protocol::HealthReport, (POS: Protocol contract.)
- manager::run_all_diagnostics, (POS: Provides register_diagnostic, register_protocol, run_all_diagnostics.)

[OUTPUT]
- HealthReport, HealthStatus, DiagnosticProtocol
- run_all_diagnostics, register_diagnostic, register_protocol

[POS]
Provides a unified diagnostic protocol for the Harness framework.
Part of the observability package — active health probing and benchmarking.
"""

import myrm_agent_harness.observability.diagnostics.gateway_health  # side-effect: registers gateway runtime probe
import myrm_agent_harness.observability.diagnostics.probes  # side-effect: registers health probes
import myrm_agent_harness.observability.diagnostics.supply_chain  # side-effect: registers supply chain probe
import myrm_agent_harness.observability.diagnostics.system_exhaustion  # side-effect: registers system exhaustion probe
import myrm_agent_harness.observability.diagnostics.system_resources  # noqa: F401  # side-effect: registers system resource probe

from .manager import register_diagnostic, register_protocol, run_all_diagnostics
from .performance import register_benchmark, run_all_benchmarks
from .protocols import DiagnosticProtocol, HealthReport, HealthStatus
from .system_exhaustion import check_system_exhaustion, get_system_exhaustion_snapshot

__all__ = [
    "DiagnosticProtocol",
    "HealthReport",
    "HealthStatus",
    "check_system_exhaustion",
    "get_system_exhaustion_snapshot",
    "register_benchmark",
    "register_diagnostic",
    "register_protocol",
    "run_all_benchmarks",
    "run_all_diagnostics",
]
