"""
[POS] src/myrm_agent_harness/core/security/event_capability_attenuation/__init__.py
[INPUT] .async_approval_bridge, .attenuation_capsule, .event_signature_verifier, .facade, .types
[OUTPUT] Public API exports for event capability attenuation subsystem

Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .async_approval_bridge import AsyncApprovalBridge
from .attenuation_capsule import CapabilityAttenuationCapsule
from .event_signature_verifier import EventSignatureVerifier
from .facade import EventCapabilityAttenuationFacade
from .types import (
    ApprovalTicket,
    ApprovalTicketStatusEnum,
    AttenuationRule,
    CapabilityAttenuationMetrics,
    ChannelNotificationTarget,
    EventPayloadDescriptor,
    EventTrustScopeEnum,
    TicketRiskLevelEnum,
)

__all__ = [
    "ApprovalTicket",
    "ApprovalTicketStatusEnum",
    "AsyncApprovalBridge",
    "AttenuationRule",
    "CapabilityAttenuationCapsule",
    "CapabilityAttenuationMetrics",
    "ChannelNotificationTarget",
    "EventCapabilityAttenuationFacade",
    "EventPayloadDescriptor",
    "EventSignatureVerifier",
    "EventTrustScopeEnum",
    "TicketRiskLevelEnum",
]
