"""Domain types and models for Streaming Endpoint Identity Gate Parity.

[INPUT]
- None.

[OUTPUT]
- Typed dataclasses and enums representing streaming transport contracts,
  identity tokens, gate access verdicts, and parity violation audits.

[POS]
- Harness core domain models ensuring streaming endpoints (SSE / WebSocket / Chunked)
  enforce strict identity and resource-scoped authorization parity with REST endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class StreamingTransport(StrEnum):
    """Network transport protocol of streaming endpoint."""

    SERVER_SENT_EVENTS = "SSE"
    WEBSOCKET = "WEBSOCKET"
    CHUNKED_STREAM = "CHUNKED_STREAM"


class GateDecision(StrEnum):
    """Access decision produced by streaming gate evaluation."""

    ALLOWED = "ALLOWED"
    DENIED_UNAUTHENTICATED = "DENIED_UNAUTHENTICATED"
    DENIED_SCOPE_MISMATCH = "DENIED_SCOPE_MISMATCH"
    DENIED_RESOURCE_UNBOUND = "DENIED_RESOURCE_UNBOUND"
    DENIED_REMOTE_BLOCKED = "DENIED_REMOTE_BLOCKED"


@dataclass(frozen=True)
class StreamingEndpointContract:
    """Declared security contract for a streaming endpoint."""

    endpoint_path: str
    transport: StreamingTransport
    requires_auth: bool = True
    required_scope: str | None = None
    target_resource_type: str | None = None  # e.g., "chat", "task", "eval", "notification"
    supports_remote_access: bool = True


@dataclass(frozen=True)
class StreamingClientIdentity:
    """Resolved client identity asserting access to a streaming connection."""

    subject_id: str | None
    auth_source: str | None
    granted_scopes: tuple[str, ...] = field(default_factory=tuple)
    bound_resource_ids: tuple[str, ...] = field(default_factory=tuple)
    is_loopback: bool = False
    is_remote: bool = False


@dataclass(frozen=True)
class StreamingGateVerdict:
    """Outcome of identity gate evaluation for a streaming request."""

    decision: GateDecision
    endpoint_path: str
    reason: str
    status_code: int


@dataclass(frozen=True)
class StreamingParityAuditIssue:
    """Detected parity defect where a streaming endpoint lacks required REST-grade security."""

    endpoint_path: str
    transport: StreamingTransport
    issue_type: str
    description: str
    severity: str


class StreamingGateError(Exception):
    """Base exception for streaming gate violations."""


class StreamingAccessDeniedError(StreamingGateError):
    """Raised when an unauthenticated or unauthorized client attempts to subscribe to a stream."""
