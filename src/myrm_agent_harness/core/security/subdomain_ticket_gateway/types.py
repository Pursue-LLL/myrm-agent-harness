"""
[POS] src/myrm_agent_harness/core/security/subdomain_ticket_gateway/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] TicketValidationStatus, AirgapAccessVerdict, OneTimeExchangeTicket, InstanceSessionContext, AirgapEvaluationResult, SubdomainGatewayMetrics

Domain data structures for Short-Lived Ticket Session Exchange & Subdomain Isolated Gateway Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TicketValidationStatus(StrEnum):
    """Result of evaluating a one-time exchange ticket."""

    VALID = "VALID"
    EXPIRED = "EXPIRED"
    ALREADY_CONSUMED = "ALREADY_CONSUMED"
    FINGERPRINT_MISMATCH = "FINGERPRINT_MISMATCH"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"


class AirgapAccessVerdict(StrEnum):
    """Enforcement outcome of subdomain least-privilege airgap guard."""

    ALLOWED_SANDBOX_LOCAL = "ALLOWED_SANDBOX_LOCAL"
    BLOCKED_MASTER_CONTROL_PLANE_ATTEMPT = "BLOCKED_MASTER_CONTROL_PLANE_ATTEMPT"
    BLOCKED_CROSS_INSTANCE_ATTEMPT = "BLOCKED_CROSS_INSTANCE_ATTEMPT"


@dataclass(frozen=True)
class OneTimeExchangeTicket:
    """Short-lived, single-use ticket for cross-subdomain instance session handshakes."""

    ticket_id: str
    master_user_id: str
    target_instance_id: str
    client_ip: str
    client_fingerprint: str
    expires_at: float
    signature: str
    is_consumed: bool = False


@dataclass(frozen=True)
class InstanceSessionContext:
    """Isolated session context minted for a specific sandbox instance subdomain."""

    session_id: str
    instance_id: str
    user_id: str
    issued_at: float
    expires_at: float
    is_revoked: bool = False


@dataclass(frozen=True)
class AirgapEvaluationResult:
    """Outcome of inspecting an egress API call against subdomain airgap rules."""

    is_allowed: bool
    verdict: AirgapAccessVerdict
    requested_path: str
    target_instance_id: str
    diagnostic_reason: str


@dataclass
class SubdomainGatewayMetrics:
    """Cumulative operational metrics for ticket exchange and subdomain airgap enforcement."""

    tickets_issued_total: int = 0
    tickets_redeemed_total: int = 0
    replay_attacks_blocked_total: int = 0
    airgap_violations_blocked_total: int = 0
    active_sessions_total: int = 0
