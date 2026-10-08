"""Domain types and models for Causal Deception Defense & Mechanism Probe.

[INPUT]
- None.

[OUTPUT]
- Typed dataclasses and enums representing commitments, execution traces,
  post-report claims, invariance verdicts, and counterfactual audience probes.

[POS]
- Pure core domain models for causal deception defense based on arXiv:2609.04166.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

JsonScalar = str | int | float | bool | None


class CommitmentType(StrEnum):
    """Categorization of commitments stated prior to tool execution."""

    TEST_RUN = "TEST_RUN"
    CODE_MODIFICATION = "CODE_MODIFICATION"
    FILE_READ = "FILE_READ"
    EXTERNAL_API_CALL = "EXTERNAL_API_CALL"
    COMMAND_EXECUTION = "COMMAND_EXECUTION"


class ClaimStatus(StrEnum):
    """Claimed outcome reported in post-execution summary."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    MODIFIED = "MODIFIED"
    VERIFIED = "VERIFIED"
    SKIPPED = "SKIPPED"


class InvarianceVerdict(StrEnum):
    """Verdict of commitment-execution-report invariance matching."""

    MATCH = "MATCH"
    UNVERIFIED_CLAIM = "UNVERIFIED_CLAIM"
    PHANTOM_EXECUTION = "PHANTOM_EXECUTION"
    DECEPTIVE_FABRICATION = "DECEPTIVE_FABRICATION"


class TechnicalProficiency(StrEnum):
    """Technical knowledge tier of the target report recipient."""

    NOVICE = "NOVICE"
    INTERMEDIATE = "INTERMEDIATE"
    SENIOR_ENGINEER = "SENIOR_ENGINEER"


@dataclass(frozen=True)
class CommitmentItem:
    """Explicit action commitment stated in planning or initial turn statement."""

    commitment_id: str
    commitment_type: CommitmentType
    target_subject: str
    description: str


@dataclass(frozen=True)
class ExecutionTraceItem:
    """Objective physical execution record from runtime tool invocation logs."""

    trace_id: str
    tool_name: str
    arguments: Mapping[str, JsonScalar] = field(default_factory=dict)
    output_summary: str = ""
    is_success: bool = True
    timestamp: str = ""


@dataclass(frozen=True)
class PostReportClaim:
    """Specific fact or achievement asserted in the model's post-execution report."""

    claim_id: str
    commitment_type: CommitmentType
    claimed_status: ClaimStatus
    target_subject: str
    assertion_text: str


@dataclass(frozen=True)
class InvarianceViolation:
    """Discrepancy detected between claims and verified physical execution."""

    claim_id: str
    verdict: InvarianceVerdict
    reason: str
    target_subject: str


@dataclass(frozen=True)
class CausalAuditReport:
    """Complete audit verdict evaluating commitment vs execution vs report consistency."""

    is_consistent: bool
    total_commitments: int
    total_traces: int
    total_claims: int
    violations: tuple[InvarianceViolation, ...] = field(default_factory=tuple)
    overall_verdict: InvarianceVerdict = InvarianceVerdict.MATCH
    risk_score: float = 0.0


@dataclass(frozen=True)
class CounterfactualProbeResult:
    """Result of testing output invariance against audience technical vulnerabilities."""

    probe_id: str
    baseline_audience: TechnicalProficiency
    adversarial_audience: TechnicalProficiency
    is_asymmetric_deception: bool
    discrepancy_details: str
    vulnerability_index: float


class CausalDeceptionError(Exception):
    """Base exception for causal deception defense failures."""


class DeceptiveFabricationDetectedError(CausalDeceptionError):
    """Raised when model asserts completion without backing physical execution traces."""


class PhantomExecutionError(CausalDeceptionError):
    """Raised when model claims to have run tools that were never invoked."""
