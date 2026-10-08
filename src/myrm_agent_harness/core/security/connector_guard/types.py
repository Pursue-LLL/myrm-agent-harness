"""Data types and models for Connector Host Allowlist and Anti-Exfiltration SSRF Guard."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


def _utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(UTC)


class GuardDecision(StrEnum):
    """Enforcement decision produced by the anti-exfiltration outbound guard."""

    INJECT_CREDENTIALS = "inject_credentials"
    ZERO_CREDENTIAL_ALLOW = "zero_credential_allow"
    BLOCK = "block"


class ThreatKind(StrEnum):
    """Classification of outbound exfiltration or SSRF threat."""

    SSRF_METADATA = "ssrf_metadata"
    SSRF_PRIVATE_IP = "ssrf_private_ip"
    HOST_SPOOFING = "host_spoofing"
    TOKEN_SMUGGLING = "token_smuggling"
    REDIRECT_EXFILTRATION = "redirect_exfiltration"
    UNREGISTERED_HOST = "unregistered_host"


class EnterpriseOutboundMode(StrEnum):
    """Operational mode for unregistered external hosts."""

    STRICT_BLOCK_UNREGISTERED = "strict_block_unregistered"
    ZERO_CRED_PERMISSIVE = "zero_cred_permissive"


@dataclass(frozen=True, slots=True)
class ConnectorAllowlistEntry:
    """Registered official endpoints and network restrictions for a connector."""

    connector_id: str
    official_hosts: tuple[str, ...]
    allow_subdomains: bool = False
    allowed_schemes: tuple[str, ...] = ("https",)
    allow_private_ip: bool = False
    description: str = ""


@dataclass(frozen=True, slots=True)
class OutboundTrafficInspection:
    """Outbound traffic payload presented to the guard for vetting."""

    url: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)
    connector_id: str | None = None
    session_id: str = "default_session"


@dataclass(frozen=True, slots=True)
class InspectionResult:
    """Evaluation result with security decision and sanitized headers."""

    decision: GuardDecision
    reason: str
    detected_threat: ThreatKind | None
    sanitized_headers: dict[str, str]
    can_inject_credential: bool
    matched_connector_id: str | None


@dataclass(frozen=True, slots=True)
class ExfiltrationThreatAlert:
    """Structured security alert raised when exfiltration or SSRF is detected."""

    alert_id: str
    session_id: str
    url: str
    threat_kind: ThreatKind
    description: str
    blocked: bool
    timestamp: datetime = field(default_factory=_utc_now)
