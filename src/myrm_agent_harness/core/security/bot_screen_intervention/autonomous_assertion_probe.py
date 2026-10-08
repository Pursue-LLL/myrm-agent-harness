"""
[POS] src/myrm_agent_harness/core/security/bot_screen_intervention/autonomous_assertion_probe.py
[INPUT] logging, typing, .types
[OUTPUT] BotScreenAssertionProbeRunner

Autonomous screen action assertion runner performing post-execution UI state verification.
Ensures critical workflows (e.g., invoices paid, tables updated, toasts displayed)
satisfy visual and DOM assertions before considering actions complete.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .types import ScreenAssertionProbe

logger = logging.getLogger(__name__)


class BotScreenAssertionProbeRunner:
    """Verifies screen outcomes against expected DOM content and visual snapshot assertions."""

    def verify_screen_assertion(
        self,
        probe_id: str,
        expected_selector: str,
        expected_text_contains: str,
        actual_text: str,
        visual_hash_match: bool,
    ) -> ScreenAssertionProbe:
        """Evaluate DOM text match and visual snapshot fidelity."""
        text_passed = expected_text_contains.lower() in actual_text.lower()
        passed = text_passed and visual_hash_match

        reasons: list[str] = []
        if not text_passed:
            reasons.append(
                f"Expected text '{expected_text_contains}' not found in actual content '{actual_text[:100]}'."
            )
        if not visual_hash_match:
            reasons.append("Visual snapshot hash diverged from baseline template.")

        detail = (
            "Screen state asserted successfully: DOM text and visual snapshot match expected state."
            if passed
            else "; ".join(reasons)
        )

        if not passed:
            logger.warning("Screen assertion probe '%s' failed on selector '%s': %s", probe_id, expected_selector, detail)
        else:
            logger.info("Screen assertion probe '%s' passed on selector '%s'.", probe_id, expected_selector)

        return ScreenAssertionProbe(
            probe_id=probe_id,
            expected_selector=expected_selector,
            expected_text_contains=expected_text_contains,
            actual_text=actual_text,
            visual_hash_match=visual_hash_match,
            passed=passed,
            detail=detail,
        )
