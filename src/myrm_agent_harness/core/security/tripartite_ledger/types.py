"""Types and data structures for Tripartite Isolation & Immutable Audit Ledger.

Enforces tripartite records architecture (Event Stream, Runtime State, Audit Ledger),
strict three-state action semantics (Replay Log, Offline Eval, Re-Execute),
and zero-knowledge ops control.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# Recursive JSON value type without Any
JsonScalar = str | int | float | bool | None
JsonType = JsonScalar | list["JsonType"] | dict[str, "JsonType"]


class ActionSemanticMode(StrEnum):
    """Semantic action mode separating replay, evaluation, and live execution."""

    REPLAY_LOG = "REPLAY_LOG"
    OFFLINE_EVAL = "OFFLINE_EVAL"
    RE_EXECUTE = "RE_EXECUTE"


class LayerType(StrEnum):
    """Tripartite records architecture layers."""

    EVENT_STREAM = "EVENT_STREAM"
    RUNTIME_STATE = "RUNTIME_STATE"
    AUDIT_LEDGER = "AUDIT_LEDGER"


@dataclass(frozen=True)
class AuditEvidenceRecord:
    """Immutable Layer-3 audit record with cryptographic hash chain."""

    record_id: str
    sequence_number: int
    prev_hash: str
    record_hash: str
    who_user_id: str
    who_agent_id: str
    when_timestamp: str
    rule_version_hash: str
    tool_name: str
    tool_call_args_hash: str
    sanitized_args_snapshot: dict[str, JsonScalar]
    connector_source: str
    connector_scope: str
    authorized_parameters_hash: str
    reconcile_receipt: str


@dataclass(frozen=True)
class AuditLedgerVerificationResult:
    """Outcome of validating the immutable audit ledger cryptographic chain."""

    is_valid: bool
    total_records: int
    corrupted_record_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class OpsTelemetryRecord:
    """Zero-knowledge operational telemetry record without business payloads."""

    task_id: str
    agent_id: str
    runtime_ms: int
    memory_bytes: int
    state: str


@dataclass(frozen=True)
class ActionExecutionResult:
    """Result of attempting an action under semantic mode boundaries."""

    mode: ActionSemanticMode
    tool_name: str
    executed: bool
    is_simulated: bool
    result: str
    audit_record_id: str | None = None


class TripartiteLedgerError(Exception):
    """Base error for tripartite ledger domain."""


class AuditIntegrityError(TripartiteLedgerError):
    """Raised when ledger integrity verification fails or tampering is detected."""


class ActionSemanticViolationError(TripartiteLedgerError):
    """Raised when an action violates semantic boundary (e.g. replay triggering side-effects)."""


class PreIOAuditAssertionError(TripartiteLedgerError):
    """Raised when a live external I/O action is attempted without pre-persisted audit record."""
