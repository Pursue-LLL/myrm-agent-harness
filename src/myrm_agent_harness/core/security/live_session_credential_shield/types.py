"""
[POS] src/myrm_agent_harness/core/security/live_session_credential_shield/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] AirlockChannelStatus, SensitiveTargetType, BoundingBox, BlindCredentialInputEvent, ScreenMaskRegion, DOMRedactionRule, MaskingRedactionReport, LiveSessionShieldMetrics

Data structures and specifications for Live Session Out-of-Band Credential Input Shield Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AirlockChannelStatus(StrEnum):
    """Operational status of the out-of-band input airlock channel."""

    OPEN = "OPEN"
    LOCKED = "LOCKED"
    BLIND_ROUTING = "BLIND_ROUTING"
    CLOSED = "CLOSED"


class SensitiveTargetType(StrEnum):
    """Classification of targeted confidential input elements."""

    PASSWORD_INPUT = "PASSWORD_INPUT"
    OTP_INPUT = "OTP_INPUT"
    API_KEY_FIELD = "API_KEY_FIELD"
    PAYMENT_CVV = "PAYMENT_CVV"
    GENERIC_CREDENTIAL = "GENERIC_CREDENTIAL"


@dataclass(frozen=True)
class BoundingBox:
    """Rectangular pixel coordinate region on the screen."""

    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class BlindCredentialInputEvent:
    """Event metadata of credentials routed out-of-band without exposing raw text to Agent."""

    session_id: str
    target_selector: str
    target_type: SensitiveTargetType
    keystroke_count: int
    is_blind_routed: bool
    timestamp: float


@dataclass(frozen=True)
class ScreenMaskRegion:
    """Designated bounding box where opaque pixel masking must be applied."""

    region_id: str
    box: BoundingBox
    mask_color: str
    target_selector: str


@dataclass(frozen=True)
class DOMRedactionRule:
    """Rule specifying DOM node attributes to redact prior to LLM observation."""

    selector_pattern: str
    attribute_to_redact: str
    replacement_value: str = "<REDACTED_CREDENTIAL>"


@dataclass(frozen=True)
class MaskingRedactionReport:
    """Audit report generated upon handing over session control back to Agent."""

    session_id: str
    masked_regions_count: int
    redacted_dom_nodes_count: int
    observation_scrubbed: bool
    timestamp: float


@dataclass
class LiveSessionShieldMetrics:
    """Cumulative operational metrics for out-of-band credential shielding."""

    blind_inputs_routed_total: int = 0
    screen_masks_applied_total: int = 0
    dom_nodes_redacted_total: int = 0
    handover_scrubs_completed_total: int = 0
    prompt_injections_mitigated_total: int = 0
