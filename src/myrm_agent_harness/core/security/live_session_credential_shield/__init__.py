"""
[POS] src/myrm_agent_harness/core/security/live_session_credential_shield/__init__.py
[INPUT] .facade, .types
[OUTPUT] LiveSessionCredentialShieldSuite, OutOfBandAirlock, PostTakeoverMasker, ...

Live Session Out-of-Band Credential Input Shield Suite.
Guards credentials during human takeover sessions and obscures confidential inputs from agent observations.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .facade import LiveSessionCredentialShieldSuite
from .out_of_band_airlock import OutOfBandAirlock
from .post_takeover_masker import PostTakeoverMasker
from .types import (
    AirlockChannelStatus,
    BlindCredentialInputEvent,
    BoundingBox,
    DOMRedactionRule,
    LiveSessionShieldMetrics,
    MaskingRedactionReport,
    ScreenMaskRegion,
    SensitiveTargetType,
)

__all__ = [
    "AirlockChannelStatus",
    "BlindCredentialInputEvent",
    "BoundingBox",
    "DOMRedactionRule",
    "LiveSessionCredentialShieldSuite",
    "LiveSessionShieldMetrics",
    "MaskingRedactionReport",
    "OutOfBandAirlock",
    "PostTakeoverMasker",
    "ScreenMaskRegion",
    "SensitiveTargetType",
]
