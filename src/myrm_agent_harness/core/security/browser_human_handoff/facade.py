"""
[POS] src/myrm_agent_harness/core/security/browser_human_handoff/facade.py
[INPUT] typing, .types, .captcha_confirm_interceptor, .browser_lease_manager, .zero_content_watchdog
[OUTPUT] BrowserHumanHandoffGateSuite

Unified Facade for Default Captcha & Confirm Screen Human Handoff Gate Suite.
Orchestrates mandatory human handoffs, mutual-exclusion browser leases,
and zero-content corruption probes.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import time

from .browser_lease_manager import BrowserProfileLeaseManager
from .captcha_confirm_interceptor import CaptchaConfirmInterceptor
from .types import (
    BrowserHumanHandoffMetrics,
    BrowserProfileLease,
    DOMContentHealthInspection,
    HandoffInterceptionResult,
    HandoffTriggerType,
)
from .zero_content_watchdog import ZeroContentDOMWatchdog

logger = logging.getLogger(__name__)


class BrowserHumanHandoffGateSuite:
    """Unified security suite enforcing human fallback for browser challenges, leases, and DOM integrity."""

    def __init__(
        self,
        interceptor: CaptchaConfirmInterceptor | None = None,
        lease_manager: BrowserProfileLeaseManager | None = None,
        watchdog: ZeroContentDOMWatchdog | None = None,
    ) -> None:
        self._interceptor = interceptor or CaptchaConfirmInterceptor()
        self._lease_manager = lease_manager or BrowserProfileLeaseManager()
        self._watchdog = watchdog or ZeroContentDOMWatchdog()
        self._metrics = BrowserHumanHandoffMetrics()

    @property
    def metrics(self) -> BrowserHumanHandoffMetrics:
        """Retrieve cumulative metrics for the browser human handoff suite."""
        return self._metrics

    def inspect_page_safety(
        self,
        html_or_dom: str,
        url: str = "",
    ) -> tuple[HandoffInterceptionResult, DOMContentHealthInspection]:
        """Comprehensive inspection of DOM health and human handoff triggers."""
        # 1. Inspect for Captcha challenges and confirm screens first
        interception = self._interceptor.inspect_page(html_or_dom, url=url)
        if interception.is_handoff_required:
            if interception.trigger_type == HandoffTriggerType.CAPTCHA_CHALLENGE:
                self._metrics.captcha_interceptions_total += 1
            elif interception.trigger_type == HandoffTriggerType.CONFIRM_SCREEN:
                self._metrics.confirm_screens_intercepted_total += 1
            # Still perform health inspection for diagnostics
            health = self._watchdog.inspect_dom_health(html_or_dom, url=url)
            return interception, health

        # 2. Inspect DOM content health for silent whiteout corruptions
        health = self._watchdog.inspect_dom_health(html_or_dom, url=url)
        if health.is_corrupted_zero_content:
            self._metrics.zero_content_corruptions_detected_total += 1
            # If DOM is corrupted/empty, wrap into a mandatory zero-content handoff
            interception = HandoffInterceptionResult(
                interception_id=f"handoff-zero-{int(time.time() * 1000)}",
                trigger_type=HandoffTriggerType.ZERO_CONTENT_CORRUPTION,
                matched_selector="DOM_BODY_EMPTY",
                is_handoff_required=True,
                explanation=health.diagnosis,
                is_resolved=False,
                timestamp=health.timestamp,
            )
            return interception, health

        return interception, health

    def resolve_handoff(self, interception_id: str) -> HandoffInterceptionResult:
        """Mark a pending handoff gate as resolved by human operator."""
        resolved = self._interceptor.resolve_interception(interception_id)
        self._metrics.handoffs_resolved_total += 1
        return resolved

    def list_pending_handoffs(self) -> list[HandoffInterceptionResult]:
        """List active screens currently waiting for human intervention."""
        return self._interceptor.list_pending_interceptions()

    def acquire_profile_lease(
        self,
        profile_name: str,
        consumer_id: str,
        ttl_seconds: float = 300.0,
    ) -> BrowserProfileLease:
        """Acquire exclusive session lock on a logged-in browser profile."""
        lease = self._lease_manager.acquire_lease(profile_name, consumer_id, ttl_seconds=ttl_seconds)
        self._metrics.browser_leases_granted_total += 1
        return lease

    def release_profile_lease(self, lease_id: str) -> BrowserProfileLease:
        """Release exclusive lock on a browser profile."""
        released = self._lease_manager.release_lease(lease_id)
        self._metrics.browser_leases_released_total += 1
        return released

    def get_active_lease(self, profile_name: str) -> BrowserProfileLease | None:
        """Query active lease on a specific profile."""
        return self._lease_manager.get_active_lease(profile_name)

    def list_active_leases(self) -> list[BrowserProfileLease]:
        """List all currently active non-expired browser profile leases."""
        return self._lease_manager.list_active_leases()
