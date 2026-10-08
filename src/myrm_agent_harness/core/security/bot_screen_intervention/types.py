"""
[POS] src/myrm_agent_harness/core/security/bot_screen_intervention/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] ScreenRiskTier, ApprovalDecision, ScreenElementAction, InterventionEvent, InterventionEvidenceBundle, ScreenAssertionProbe, BotScreenOperationalMetrics

Domain types for Bot Screen Auditable Operational Control & Intervention Evidence Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ScreenRiskTier(StrEnum):
    """Risk tier for screen elements and user interactions."""

    SAFE_READONLY = "SAFE_READONLY"
    STANDARD_WRITE = "STANDARD_WRITE"
    HIGH_RISK_FINANCIAL = "HIGH_RISK_FINANCIAL"
    CRITICAL_ADMIN = "CRITICAL_ADMIN"


class ApprovalDecision(StrEnum):
    """Outcome of evaluating screen action operational boundaries."""

    APPROVED_AUTOMATIC = "APPROVED_AUTOMATIC"
    PENDING_HUMAN_APPROVAL = "PENDING_HUMAN_APPROVAL"
    REJECTED = "REJECTED"
    MANUAL_TAKEOVER_REQUIRED = "MANUAL_TAKEOVER_REQUIRED"


@dataclass(frozen=True)
class ScreenElementAction:
    """Action intended on a screen UI element."""

    action_id: str
    target_selector: str
    action_type: str  # e.g., "click", "type", "submit", "select"
    label: str
    value_masked: str
    risk_tier: ScreenRiskTier


@dataclass(frozen=True)
class InterventionEvent:
    """User input event recorded during human takeover intervention."""

    event_id: str
    event_type: str  # e.g., "mouse_click", "keyboard_input", "scroll"
    target_selector: str
    timestamp: float
    data_sanitized: str


@dataclass(frozen=True)
class InterventionEvidenceBundle:
    """Cryptographically anchored tamper-proof intervention audit bundle."""

    session_id: str
    intervention_id: str
    operator_id: str
    start_time: float
    end_time: float
    before_snapshot_hash: str
    after_snapshot_hash: str
    event_count: int
    bundle_sha256: str
    is_tamper_evident: bool


@dataclass(frozen=True)
class ScreenAssertionProbe:
    """Autonomous post-execution UI state assertion probe."""

    probe_id: str
    expected_selector: str
    expected_text_contains: str
    actual_text: str
    visual_hash_match: bool
    passed: bool
    detail: str


@dataclass
class BotScreenOperationalMetrics:
    """Operational metrics for screen interventions and approval gates."""

    total_screen_actions: int = 0
    approval_checkpoints_triggered: int = 0
    manual_takeovers_conducted: int = 0
    assertion_failures: int = 0
    evidence_bundles_sealed: int = 0
