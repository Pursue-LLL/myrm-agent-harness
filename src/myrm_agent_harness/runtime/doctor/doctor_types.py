"""Strongly typed data contracts for system doctor and capability assertion verifier.

[OUTPUT]
- CheckSeverity: Severity classification of an individual health check (INFO, PASS, WARN, FAIL).
- DoctorCategory: Four-dimensional diagnostic domain (CONFIG, MODEL, RUNTIME_SANDBOX, NETWORK_EGRESS, CAPABILITY).
- CheckFinding: Outcome and remediation advice of a single doctor probe.
- CapabilityAssertion: Real-world operational verification of a declared tool or skill.
- DoctorReport: Aggregated system-wide health diagnosis and capability assertions.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- CheckSeverity
- DoctorCategory
- CheckFinding
- CapabilityAssertion
- DoctorReport

[POS]
Strongly typed data contracts for system doctor and capability assertion verifier.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class CheckSeverity(StrEnum):
    """Result severity of a single health inspection item."""

    INFO = "info"
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class DoctorCategory(StrEnum):
    """Diagnostic dimension of the system doctor."""

    CONFIG = "config"
    MODEL = "model"
    RUNTIME_SANDBOX = "runtime_sandbox"
    NETWORK_EGRESS = "network_egress"
    CAPABILITY = "capability"


@dataclass(frozen=True)
class CheckFinding:
    """Detailed result of an individual health check."""

    name: str
    category: DoctorCategory
    severity: CheckSeverity
    message: str
    detail: str = ""
    remediation_hint: str = ""
    is_auto_fixable: bool = False


@dataclass(frozen=True)
class CapabilityAssertion:
    """Verification receipt comparing declared capability against real execution readiness."""

    name: str
    kind: str
    declared: bool
    verified: bool
    latency_ms: float = 0.0
    error_detail: str | None = None

    @property
    def is_consistent(self) -> bool:
        """True if the capability declared state matches real environment readiness."""
        return self.declared == self.verified


@dataclass(frozen=True)
class DoctorReport:
    """Full-spectrum diagnostic report of system health and verified agent capabilities."""

    findings: tuple[CheckFinding, ...] = field(default_factory=tuple)
    capabilities: tuple[CapabilityAssertion, ...] = field(default_factory=tuple)
    overall_healthy: bool = True
    pass_count: int = 0
    warn_count: int = 0
    fail_count: int = 0
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def assemble(
        cls,
        findings: list[CheckFinding] | tuple[CheckFinding, ...],
        capabilities: list[CapabilityAssertion] | tuple[CapabilityAssertion, ...],
        duration_ms: float = 0.0,
    ) -> DoctorReport:
        """Assemble findings and capabilities into a summarized report."""
        p_count = sum(1 for f in findings if f.severity == CheckSeverity.PASS)
        w_count = sum(1 for f in findings if f.severity == CheckSeverity.WARN)
        f_count = sum(1 for f in findings if f.severity == CheckSeverity.FAIL)
        # Any failing check or declared-but-unverified capability marks overall unhealthy
        cap_failures = sum(1 for c in capabilities if c.declared and not c.verified)
        is_healthy = f_count == 0 and cap_failures == 0

        return cls(
            findings=tuple(findings),
            capabilities=tuple(capabilities),
            overall_healthy=is_healthy,
            pass_count=p_count,
            warn_count=w_count,
            fail_count=f_count + cap_failures,
            duration_ms=round(duration_ms, 2),
        )
