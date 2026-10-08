"""Type definitions for Pre-Action Side-Effect Gate and Post-Run Acceptance.

[INPUT]
None - pure types and structured contracts.

[OUTPUT]
- SideEffectType, PreActionRiskLevel, PreActionStatus
- PreActionChallenge, ActionReceipt
- AcceptanceRuleType, AcceptanceRule, AcceptanceViolation, AcceptanceReport
- PreActionApprovalRequiredException, PreActionDeniedException

[POS]
Harness security core. Defines contracts separating pre-action irreversible execution
authorization from post-run delivery quality acceptance.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class SideEffectType(StrEnum):
    """Classification of tool operation side-effect impact."""

    READ_ONLY = "read_only"
    WORKSPACE_LOCAL = "workspace_local"
    MUTATING_EXTERNAL = "mutating_external"


class PreActionRiskLevel(StrEnum):
    """Assessed risk level of intercepted mutating action."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PreActionStatus(StrEnum):
    """Lifecycle status of a pre-action authorization challenge."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    BYPASSED = "bypassed"


type ActionArgumentValue = str | int | float | bool | None | list[str] | dict[str, str]
type ActionArguments = dict[str, ActionArgumentValue]


@dataclass(frozen=True, slots=True)
class PreActionChallenge:
    """Challenge issued when a mutating external tool call is physically intercepted."""

    challenge_id: str
    session_id: str
    tool_name: str
    arguments: ActionArguments
    idempotency_key: str
    risk_level: PreActionRiskLevel
    summary: str
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 600.0)

    def is_expired(self, current_time: float | None = None) -> bool:
        """Check if challenge has passed its validity window."""
        now = time.time() if current_time is None else current_time
        return now > self.expires_at


@dataclass(frozen=True, slots=True)
class ActionReceipt:
    """Tamper-evident receipt representing successful execution of an external action."""

    idempotency_key: str
    tool_name: str
    provider_receipt_id: str
    status: str
    output_summary: str
    challenge_id: str | None = None
    recorded_at: float = field(default_factory=time.time)


class AcceptanceRuleType(StrEnum):
    """Deterministic validation rule categories for post-run deliverables."""

    NON_EMPTY = "non_empty"
    LENGTH_BOUNDS = "length_bounds"
    REQUIRED_STRUCTURE = "required_structure"
    REQUIRED_JSON_KEYS = "required_json_keys"
    NUMERICAL_SUM_EQUALS = "numerical_sum_equals"


@dataclass(frozen=True, slots=True)
class AcceptanceRule:
    """Individual deterministic quality rule for post-run acceptance verification."""

    rule_type: AcceptanceRuleType
    description: str
    min_length: int | None = None
    max_length: int | None = None
    required_sections: list[str] | None = None
    required_json_keys: list[str] | None = None
    sum_field_names: list[str] | None = None
    total_field_name: str | None = None


@dataclass(frozen=True, slots=True)
class AcceptanceViolation:
    """Specific rule violation detected during post-run deterministic acceptance."""

    rule_type: AcceptanceRuleType
    message: str
    actual_value: str | int | float | None = None


@dataclass(frozen=True, slots=True)
class AcceptanceReport:
    """Summary of deterministic post-run acceptance evaluation."""

    passed: bool
    violations: list[AcceptanceViolation]
    summary: str
    evaluated_at: float = field(default_factory=time.time)


class PreActionApprovalRequiredError(Exception):
    """Raised when an action requires human pre-authorization before dispatch."""

    def __init__(self, challenge: PreActionChallenge) -> None:
        super().__init__(
            f"Pre-action approval required for tool '{challenge.tool_name}' "
            f"(challenge_id={challenge.challenge_id}, idempotency_key={challenge.idempotency_key})"
        )
        self.challenge = challenge


class PreActionDeniedError(Exception):
    """Raised when an intercepted action is explicitly rejected or expired."""

    def __init__(self, challenge_id: str, reason: str) -> None:
        super().__init__(f"Pre-action execution denied for challenge '{challenge_id}': {reason}")
        self.challenge_id = challenge_id
        self.reason = reason
