"""Types and schemas for pre-flight prefix integrity freeze and assertion barrier.

[INPUT]
System prompt strings, tool definition sequences, historical messages, and model names.

[OUTPUT]
Type-safe schemas for frozen payloads, baseline prefix locks, drift classifications,
and assertion barrier violations.

[POS]
Core protocol benchmarked against DeepSeek Harness pre-flight request freezing and log-replay assertions.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class BarrierInterceptionMode(StrEnum):
    """Enforcement policy for pre-flight prefix cache protection."""
    STRICT_ASSERTION = "strict_assertion"  # Hard block and raise error
    WARN_AUDIT_ONLY = "warn_audit_only"    # Log drift but permit execution


class PrefixDriftKind(StrEnum):
    """Specific cause of prefix cache breakdown."""
    SYSTEM_PROMPT_MUTATION = "system_prompt_mutation"
    TOOL_SCHEMA_MUTATION = "tool_schema_mutation"
    TOOL_ORDER_DRIFT = "tool_order_drift"
    MODEL_SWITCH = "model_switch"


class PrefixIntegrityViolationError(RuntimeError):
    """Raised when an unapproved pre-flight prefix mutation is blocked by the barrier."""

    def __init__(self, message: str, drift_kind: PrefixDriftKind, details: str = "") -> None:
        super().__init__(f"[{drift_kind}] {message}: {details}")
        self.drift_kind = drift_kind
        self.details = details


@dataclass(frozen=True)
class FrozenToolDescriptor:
    """Immutable tool definition descriptor for deterministic schema hashing."""
    name: str
    description: str
    parameters_schema_hash: str


@dataclass(frozen=True)
class FrozenModelPayload:
    """Deeply immutable snapshot of an outgoing model request before network dispatch."""
    session_id: str
    system_prompt: str
    system_prompt_sha256: str
    tools: tuple[FrozenToolDescriptor, ...]
    tools_fingerprint_sha256: str
    messages_count: int
    model_name: str
    frozen_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class BaselinePrefixFingerprint:
    """Golden baseline fingerprint established on initial turn for a session."""
    session_id: str
    system_prompt_sha256: str
    tools_fingerprint_sha256: str
    model_name: str
    established_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class PreFlightInspectionResult:
    """Verification outcome of pre-flight prefix integrity check."""
    session_id: str
    is_valid: bool
    is_baseline_established: bool
    drifts: tuple[PrefixDriftKind, ...] = ()
    violation_message: str | None = None
    exemption_granted: bool = False
