"""Types and contracts for Spatiotemporal Duality, Connector Trust & Declarative Saga.

Enforces:
1. ToolIntent duality: Acquisition (reversible, read-only) vs Emission (irreversible, physical I/O).
2. Connector trust leasing (explicit host/scope trust gate).
3. Declarative Saga compensation and immutable emission audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

JsonScalar = str | int | float | bool | None


class ToolIntent(StrEnum):
    """Spatiotemporal duality classification of tool actions."""

    ACQUISITION = "ACQUISITION"  # Reversible, in-process state fetch (read-only, parallelizable)
    EMISSION = "EMISSION"  # Irreversible, physical cross-boundary effect (requires trust & HITL)


class CompensationStatus(StrEnum):
    """Lifecycle status of a Saga step's reverse compensation action."""

    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    COMPENSATED = "COMPENSATED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ConnectorTrustLease:
    """Explicit trust authorization grant issued to an external connector."""

    lease_id: str
    connector_id: str
    host: str
    authorized_scopes: tuple[str, ...]
    expires_at: str
    is_active: bool = True


@dataclass(frozen=True)
class SagaStep:
    """Executed operational step registered in the Saga transaction log."""

    step_id: str
    tool_name: str
    intent: ToolIntent
    params: dict[str, JsonScalar]
    compensator_name: str | None
    compensation_params: dict[str, JsonScalar]
    status: str
    executed_at: str


@dataclass(frozen=True)
class EmissionAuditRecord:
    """Immutable audit entry for physical emission operations."""

    audit_id: str
    agent_id: str
    approver_id: str
    connector_id: str
    tool_name: str
    params_hash: str
    receipt: str
    compensation_status: CompensationStatus
    timestamp: str


class SagaDualEngineError(Exception):
    """Base error for spatiotemporal duality and saga engine."""


class ConnectorUntrustedError(SagaDualEngineError):
    """Raised when an emission attempts to access an untrusted external connector."""


class EmissionUnconfirmedError(SagaDualEngineError):
    """Raised when an irreversible emission action lacks secondary HITL confirmation."""


class SagaRollbackError(SagaDualEngineError):
    """Raised when one or more Saga reverse compensating actions fail."""
