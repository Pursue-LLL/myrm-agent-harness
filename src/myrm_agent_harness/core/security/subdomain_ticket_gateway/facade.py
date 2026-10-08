"""
[POS] src/myrm_agent_harness/core/security/subdomain_ticket_gateway/facade.py
[INPUT] logging, typing, .types, .ticket_exchange_manager, .subdomain_airgap_guard
[OUTPUT] SubdomainIsolatedGatewaySuite

Unified facade for Short-Lived Ticket Session Exchange & Subdomain Isolated Gateway Suite.
Coordinates single-use anti-replay ticket issuance, isolated instance session minting,
and least-privilege airgap boundary enforcement.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .subdomain_airgap_guard import SubdomainAirgapGuard
from .ticket_exchange_manager import ShortLivedTicketExchangeManager
from .types import (
    AirgapEvaluationResult,
    InstanceSessionContext,
    OneTimeExchangeTicket,
    SubdomainGatewayMetrics,
    TicketValidationStatus,
)

logger = logging.getLogger(__name__)


class SubdomainIsolatedGatewaySuite:
    """Unified security suite safeguarding subdomain instance isolation and auth handshakes."""

    def __init__(
        self,
        exchange_manager: ShortLivedTicketExchangeManager | None = None,
        airgap_guard: SubdomainAirgapGuard | None = None,
    ) -> None:
        self._exchange_manager = exchange_manager or ShortLivedTicketExchangeManager()
        self._airgap_guard = airgap_guard or SubdomainAirgapGuard()
        self._metrics = SubdomainGatewayMetrics()

    @property
    def metrics(self) -> SubdomainGatewayMetrics:
        """Retrieve cumulative metrics."""
        return self._metrics

    def issue_exchange_ticket(
        self,
        master_user_id: str,
        target_instance_id: str,
        client_ip: str,
        client_fingerprint: str,
    ) -> OneTimeExchangeTicket:
        """Issue a 30s single-use exchange ticket from master control domain."""
        ticket = self._exchange_manager.issue_ticket(
            master_user_id=master_user_id,
            target_instance_id=target_instance_id,
            client_ip=client_ip,
            client_fingerprint=client_fingerprint,
        )
        self._metrics.tickets_issued_total += 1
        return ticket

    def redeem_exchange_ticket(
        self,
        ticket_id: str,
        client_ip: str,
        client_fingerprint: str,
    ) -> tuple[TicketValidationStatus, InstanceSessionContext | None]:
        """Validate and redeem ticket at the subdomain gateway."""
        status, session = self._exchange_manager.redeem_ticket(
            ticket_id=ticket_id,
            client_ip=client_ip,
            client_fingerprint=client_fingerprint,
        )

        if status == TicketValidationStatus.VALID and session is not None:
            self._metrics.tickets_redeemed_total += 1
            self._metrics.active_sessions_total += 1
        elif status == TicketValidationStatus.ALREADY_CONSUMED:
            self._metrics.replay_attacks_blocked_total += 1

        return status, session

    def validate_instance_session(self, session_id: str, instance_id: str) -> bool:
        """Verify validity of an isolated subdomain session token."""
        return self._exchange_manager.validate_instance_session(session_id, instance_id)

    def revoke_session(self, session_id: str) -> bool:
        """Revoke an active instance session."""
        revoked = self._exchange_manager.revoke_session(session_id)
        if revoked and self._metrics.active_sessions_total > 0:
            self._metrics.active_sessions_total -= 1
        return revoked

    def evaluate_airgap_request(
        self,
        current_instance_id: str,
        requested_path: str,
        target_instance_id: str | None = None,
    ) -> AirgapEvaluationResult:
        """Evaluate outbound API request against subdomain airgap rules."""
        result = self._airgap_guard.evaluate_egress_request(
            current_instance_id=current_instance_id,
            requested_path=requested_path,
            target_instance_id=target_instance_id,
        )
        if not result.is_allowed:
            self._metrics.airgap_violations_blocked_total += 1
        return result
