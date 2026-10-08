"""
[POS] src/myrm_agent_harness/core/security/subdomain_ticket_gateway/__init__.py
[INPUT] .types, .ticket_exchange_manager, .subdomain_airgap_guard, .facade
[OUTPUT] SubdomainIsolatedGatewaySuite, TicketValidationStatus, AirgapAccessVerdict, etc.

Export interface for Short-Lived Ticket Session Exchange & Subdomain Isolated Gateway Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .facade import SubdomainIsolatedGatewaySuite
from .subdomain_airgap_guard import SubdomainAirgapGuard
from .ticket_exchange_manager import ShortLivedTicketExchangeManager
from .types import (
    AirgapAccessVerdict,
    AirgapEvaluationResult,
    InstanceSessionContext,
    OneTimeExchangeTicket,
    SubdomainGatewayMetrics,
    TicketValidationStatus,
)

__all__ = [
    "AirgapAccessVerdict",
    "AirgapEvaluationResult",
    "InstanceSessionContext",
    "OneTimeExchangeTicket",
    "ShortLivedTicketExchangeManager",
    "SubdomainAirgapGuard",
    "SubdomainGatewayMetrics",
    "SubdomainIsolatedGatewaySuite",
    "TicketValidationStatus",
]
