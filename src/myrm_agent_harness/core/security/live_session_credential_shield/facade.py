"""
[POS] src/myrm_agent_harness/core/security/live_session_credential_shield/facade.py
[INPUT] typing
[OUTPUT] LiveSessionCredentialShieldSuite

Unified facade for Live Session Out-of-Band Credential Input Shield Suite.
Combines out-of-band blind credential airlocks with post-takeover screen masking and DOM redaction.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

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

logger = logging.getLogger(__name__)


class LiveSessionCredentialShieldSuite:
    """Unified security facade guarding credentials during live takeover sessions against prompt injection."""

    def __init__(self) -> None:
        self._airlock = OutOfBandAirlock()
        self._masker = PostTakeoverMasker()
        self._metrics = LiveSessionShieldMetrics()

    @property
    def metrics(self) -> LiveSessionShieldMetrics:
        """Cumulative operational metrics."""
        return self._metrics

    def open_airlock(self, session_id: str) -> AirlockChannelStatus:
        """Open an out-of-band input airlock for a live session."""
        return self._airlock.open_channel(session_id)

    def close_airlock(self, session_id: str) -> AirlockChannelStatus:
        """Close an out-of-band input airlock channel."""
        return self._airlock.close_channel(session_id)

    def get_airlock_status(self, session_id: str) -> AirlockChannelStatus:
        """Query channel status."""
        return self._airlock.get_channel_status(session_id)

    def route_blind_input(
        self,
        session_id: str,
        target_selector: str,
        raw_secret: str,
        target_type: SensitiveTargetType | None = None,
    ) -> tuple[BlindCredentialInputEvent, str]:
        """Route keystrokes via blind airlock channel, ensuring Agent observation is shielded."""
        self._metrics.blind_inputs_routed_total += 1
        return self._airlock.route_blind_input(
            session_id=session_id,
            target_selector=target_selector,
            raw_secret=raw_secret,
            target_type=target_type,
        )

    def register_mask_region(
        self,
        session_id: str,
        box: BoundingBox,
        target_selector: str,
        mask_color: str = "#000000",
    ) -> ScreenMaskRegion:
        """Designate a screen coordinate bounding box for opaque pixel masking."""
        self._metrics.screen_masks_applied_total += 1
        return self._masker.register_mask_region(
            session_id=session_id,
            box=box,
            target_selector=target_selector,
            mask_color=mask_color,
        )

    def list_mask_regions(self, session_id: str) -> list[ScreenMaskRegion]:
        """Retrieve all active screen mask regions for a session."""
        return self._masker.list_mask_regions(session_id)

    def redact_dom_tree(
        self,
        dom_html: str,
        custom_rules: tuple[DOMRedactionRule, ...] | None = None,
    ) -> tuple[str, int]:
        """Scrub password inputs and secret tokens from DOM HTML before providing to LLM context."""
        sanitized_dom, count = self._masker.redact_dom_tree(
            dom_html=dom_html,
            custom_rules=custom_rules,
        )
        self._metrics.dom_nodes_redacted_total += count
        if count > 0:
            self._metrics.prompt_injections_mitigated_total += 1
        return sanitized_dom, count

    def execute_handover_scrub(
        self,
        session_id: str,
        dom_html: str,
    ) -> tuple[str, MaskingRedactionReport]:
        """Atomically execute screen-DOM redactions when handing control back to Agent."""
        sanitized_dom, report = self._masker.execute_handover_scrub(
            session_id=session_id,
            dom_html=dom_html,
        )
        self._metrics.dom_nodes_redacted_total += report.redacted_dom_nodes_count
        self._metrics.handover_scrubs_completed_total += 1
        if report.redacted_dom_nodes_count > 0:
            self._metrics.prompt_injections_mitigated_total += 1
        return sanitized_dom, report

    def list_session_blind_events(self, session_id: str) -> list[BlindCredentialInputEvent]:
        """List historical blind input audit events."""
        return self._airlock.list_session_blind_events(session_id)
