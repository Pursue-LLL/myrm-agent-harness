"""
[POS] src/myrm_agent_harness/core/security/browser_human_handoff/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] HandoffTriggerType, CaptchaVendor, BrowserLeaseStatus, HandoffInterceptionResult, BrowserProfileLease, DOMContentHealthInspection, BrowserHumanHandoffMetrics

Data structures and specifications for Default Captcha & Confirm Screen Human Handoff Gate Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class HandoffTriggerType(StrEnum):
    """Reason triggering mandatory human handoff."""

    CAPTCHA_CHALLENGE = "CAPTCHA_CHALLENGE"
    CONFIRM_SCREEN = "CONFIRM_SCREEN"
    ZERO_CONTENT_CORRUPTION = "ZERO_CONTENT_CORRUPTION"


class CaptchaVendor(StrEnum):
    """Identified anti-bot captcha provider."""

    CLOUDFLARE_TURNSTILE = "CLOUDFLARE_TURNSTILE"
    RECAPTCHA = "RECAPTCHA"
    HCAPTCHA = "HCAPTCHA"
    GENERIC_CAPTCHA = "GENERIC_CAPTCHA"


class BrowserLeaseStatus(StrEnum):
    """Status of an exclusive browser profile lease."""

    AVAILABLE = "AVAILABLE"
    LEASED = "LEASED"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"


@dataclass(frozen=True)
class HandoffInterceptionResult:
    """Interception decision outcome for a browser page inspection."""

    interception_id: str
    trigger_type: HandoffTriggerType | None
    matched_selector: str
    is_handoff_required: bool
    explanation: str
    is_resolved: bool = False
    timestamp: float = 0.0


@dataclass(frozen=True)
class BrowserProfileLease:
    """Exclusive single-task lease grant on a logged-in browser profile."""

    lease_id: str
    profile_name: str
    consumer_id: str
    acquired_at: float
    ttl_seconds: float
    status: BrowserLeaseStatus


@dataclass(frozen=True)
class DOMContentHealthInspection:
    """Inspection outcome of DOM text completeness and zero-content corruption."""

    url: str
    content_length: int
    node_count: int
    is_corrupted_zero_content: bool
    diagnosis: str
    timestamp: float


@dataclass
class BrowserHumanHandoffMetrics:
    """Cumulative operational metrics for browser human handoff gate suite."""

    captcha_interceptions_total: int = 0
    confirm_screens_intercepted_total: int = 0
    zero_content_corruptions_detected_total: int = 0
    browser_leases_granted_total: int = 0
    browser_leases_released_total: int = 0
    handoffs_resolved_total: int = 0
