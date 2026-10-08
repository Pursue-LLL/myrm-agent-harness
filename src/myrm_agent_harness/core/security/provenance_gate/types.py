"""Type definitions for Session Entity Provenance Gate and Two-Stage Staging Approval Suite.

[INPUT]
None.

[OUTPUT]
- EntityProvenanceRecord, StagedChangeDraft, HostApprovalToken, CapsLimitViolation
- ProvenanceCheckError, CapsExceededError, StagedChangeNotApprovedError

[POS]
Harness core security subsystem inspired by Anthropic Commerce Agents (PROVENANCE_GATE & APPROVAL_GATE).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class StagedChangeStatus(StrEnum):
    """Lifecycle status of a two-stage proposed change."""

    STAGED = "staged"
    APPROVED = "approved"
    APPLIED = "applied"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class EntityProvenanceRecord:
    """Provenance entry verifying an entity was observed via a read tool in this session."""

    session_id: str
    entity_id: str
    entity_type: str
    source_tool: str
    observed_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class StagedChangeDraft:
    """A proposed high-impact mutation held in staging prior to host sign-off."""

    staged_id: str
    session_id: str
    target_entity_id: str
    mutation_type: str  # price_change, delete, batch_update, deduction
    diff_payload: dict[str, str | int | float | bool]
    status: StagedChangeStatus = StagedChangeStatus.STAGED
    host_token_id: str | None = None
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 300.0)


@dataclass(frozen=True, slots=True)
class HostApprovalToken:
    """Cryptographically or structurally verifiable host platform authorization token."""

    token_id: str
    staged_id: str
    operator_id: str
    signature: str
    issued_at: float = field(default_factory=time.time)
    valid_until: float = field(default_factory=lambda: time.time() + 60.0)


@dataclass(frozen=True, slots=True)
class CapsLimitViolation:
    """Specific parameter that exceeded Python hard limit guardrails."""

    parameter_name: str
    attempted_value: float
    max_allowed_value: float
    compliant_alternative: float
    message: str


class ProvenanceCheckError(Exception):
    """Raised when an un-seen or hallucinated entity ID is submitted to a write tool."""

    def __init__(self, session_id: str, entity_id: str, tool_name: str) -> None:
        super().__init__(
            f"Provenance failure in session '{session_id}': Entity '{entity_id}' has not been observed "
            f"by any read-only query tool in this session. Re-query before attempting mutation."
        )
        self.session_id = session_id
        self.entity_id = entity_id
        self.tool_name = tool_name


class CapsExceededError(Exception):
    """Raised when proposed values violate hardcoded business caps and limits."""

    def __init__(self, violations: tuple[CapsLimitViolation, ...]) -> None:
        summary = "; ".join(v.message for v in violations)
        super().__init__(f"Business caps exceeded: {summary}")
        self.violations = violations


class StagedChangeNotApprovedError(Exception):
    """Raised when apply is attempted without valid host approval token."""

    def __init__(self, staged_id: str, reason: str) -> None:
        super().__init__(f"Cannot apply staged change '{staged_id}': {reason}")
        self.staged_id = staged_id
        self.reason = reason
