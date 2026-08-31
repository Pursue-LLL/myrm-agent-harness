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

import myrm_agent_harness.observability.diagnostics.benchmark_probes
import myrm_agent_harness.observability.diagnostics.gateway_health  # noqa: F401  # side-effect: registers gateway runtime probe
import myrm_agent_harness.observability.diagnostics.probes  # side-effect: registers probes/benchmarks
import myrm_agent_harness.observability.diagnostics.supply_chain  # noqa: F401  # side-effect: registers supply chain probe
import myrm_agent_harness.observability.diagnostics.system_resources  # noqa: F401  # side-effect: registers system resource probe

from .manager import register_diagnostic, register_protocol, run_all_diagnostics
from .migration_reporter import (
    MigrationDiagnosticReport,
    MigrationFailureDetail,
    MigrationPhase,
    MigrationProgressEvent,
    MigrationProgressReporter,
)
from .performance import register_benchmark, run_all_benchmarks
from .protocols import DiagnosticProtocol, HealthReport, HealthStatus

__all__ = [
    "DiagnosticProtocol",
    "HealthReport",
    "HealthStatus",
    "MigrationDiagnosticReport",
    "MigrationFailureDetail",
    "MigrationPhase",
    "MigrationProgressEvent",
    "MigrationProgressReporter",
    "register_benchmark",
    "register_diagnostic",
    "register_protocol",
    "run_all_benchmarks",
    "run_all_diagnostics",
]
