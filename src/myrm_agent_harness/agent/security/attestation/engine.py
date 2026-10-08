"""Engine running all-vector pre-flight security integrity attestation audits.

[POS]
Executes host boundary, mount penetration, binary tampering, and TLS certificate checks.
Issues cryptographically timestamped attestation reports and enforces hard-break shutdowns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from myrm_agent_harness.agent.security.attestation.models import (
    AttestationFailedHardBreakError,
    AttestationSeverity,
    EnvironmentAttestationReport,
    VectorCheckResult,
)
from myrm_agent_harness.agent.security.attestation.probes import (
    BinaryIntegrityProbe,
    ConnectionTLSPinningProbe,
    HostIsolationProbe,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AttestationConfig:
    """Configuration specifying targets and baselines for attestation vectors."""

    check_mounts: bool = True
    binaries: dict[Path, str | None] = field(default_factory=dict)
    tls_endpoints: list[tuple[str, int, str | None]] = field(default_factory=list)


class EnvironmentAttestationEngine:
    """Core attestation engine running all-vector pre-flight audits."""

    @classmethod
    def run_preflight_audit(
        cls,
        config: AttestationConfig | None = None,
    ) -> EnvironmentAttestationReport:
        """Run all configured vector inspection probes and generate an attestation report."""
        cfg = config or AttestationConfig()
        results: list[VectorCheckResult] = []

        # Vector 1: Host Architecture & Fingerprint
        results.append(HostIsolationProbe.audit_host_fingerprint())

        # Vector 2: Mount Boundaries & Dangerous System Leaks
        if cfg.check_mounts:
            results.extend(HostIsolationProbe.audit_dangerous_mounts())

        # Vector 3: Binary & Script SHA-256 Integrity
        for path, expected_hash in cfg.binaries.items():
            results.append(BinaryIntegrityProbe.verify_binary(path, expected_hash))

        # Vector 4: Outbound TLS Pinning & MITM Probing
        for hostname, port, expected_pin in cfg.tls_endpoints:
            results.append(ConnectionTLSPinningProbe.verify_endpoint_tls(hostname, port, expected_pin))

        # Evaluate Overall Trust Status
        has_critical_failure = any(
            not r.is_valid and r.severity == AttestationSeverity.CRITICAL for r in results
        )
        overall_passed = not has_critical_failure

        summary = (
            "All runtime security vectors certified valid."
            if overall_passed
            else f"Attestation failed: {len([r for r in results if not r.is_valid])} anomaly vector(s) detected."
        )

        host_fp = results[0].actual_digest or "unknown"
        report = EnvironmentAttestationReport(
            attestation_id=f"attest-{uuid4().hex[:12]}",
            overall_passed=overall_passed,
            vector_results=tuple(results),
            host_fingerprint=host_fp,
            summary=summary,
        )

        logger.info(
            "[ATTESTATION_ENGINE] Completed preflight audit: passed=%s, vectors=%d",
            overall_passed,
            len(results),
        )
        return report

    @classmethod
    def assert_attestation_passed(
        cls,
        config: AttestationConfig | None = None,
    ) -> EnvironmentAttestationReport:
        """Run preflight audit and enforce hard-break shutdown if critical anomalies detected.

        Raises:
            AttestationFailedHardBreakError: If any critical vector fails attestation.
        """
        report = cls.run_preflight_audit(config)

        if not report.overall_passed:
            failed_targets = [f"{r.vector.value}:{r.target}" for r in report.failed_critical_vectors]
            logger.critical(
                "[ATTESTATION_ENGINE] Hard-break triggered! Failed vectors: %s",
                failed_targets,
            )
            raise AttestationFailedHardBreakError(
                message="Runtime environment integrity compromised or untrusted host penetration detected",
                failed_vectors=failed_targets,
            )

        return report
