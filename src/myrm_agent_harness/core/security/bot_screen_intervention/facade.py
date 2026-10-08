"""
[POS] src/myrm_agent_harness/core/security/bot_screen_intervention/facade.py
[INPUT] logging, typing, .types, .operational_boundary_guard, .intervention_evidence_recorder, .autonomous_assertion_probe
[OUTPUT] BotScreenAuditableControlSuite

Unified facade for Bot Screen Auditable Operational Control & Intervention Evidence Suite.
Coordinates least-privilege boundary checkpoints, tamper-proof takeover audit trails,
and autonomous post-action visual/DOM verification probes.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .autonomous_assertion_probe import BotScreenAssertionProbeRunner
from .intervention_evidence_recorder import BotScreenInterventionEvidenceRecorder
from .operational_boundary_guard import BotScreenOperationalBoundaryGuard
from .types import (
    ApprovalDecision,
    BotScreenOperationalMetrics,
    InterventionEvent,
    InterventionEvidenceBundle,
    ScreenAssertionProbe,
    ScreenElementAction,
    ScreenRiskTier,
)

logger = logging.getLogger(__name__)


class BotScreenAuditableControlSuite:
    """Unified security suite providing operational boundary enforcement and tamper-proof takeover trails."""

    def __init__(
        self,
        boundary_guard: BotScreenOperationalBoundaryGuard | None = None,
        evidence_recorder: BotScreenInterventionEvidenceRecorder | None = None,
        assertion_runner: BotScreenAssertionProbeRunner | None = None,
    ) -> None:
        self._boundary_guard = boundary_guard or BotScreenOperationalBoundaryGuard()
        self._evidence_recorder = evidence_recorder or BotScreenInterventionEvidenceRecorder()
        self._assertion_runner = assertion_runner or BotScreenAssertionProbeRunner()
        self._metrics = BotScreenOperationalMetrics()

    @property
    def metrics(self) -> BotScreenOperationalMetrics:
        """Retrieve cumulative metrics."""
        return self._metrics

    def classify_element_risk(
        self,
        selector: str,
        label: str,
        action_type: str,
    ) -> ScreenRiskTier:
        """Classify a screen element into operational risk tier."""
        return self._boundary_guard.classify_element_risk(selector, label, action_type)

    def evaluate_action(
        self,
        action: ScreenElementAction,
    ) -> tuple[ApprovalDecision, str]:
        """Evaluate screen action against least-privilege enterprise boundary rules."""
        self._metrics.total_screen_actions += 1
        decision, reason = self._boundary_guard.evaluate_action_boundary(action)

        if decision == ApprovalDecision.PENDING_HUMAN_APPROVAL:
            self._metrics.approval_checkpoints_triggered += 1
        elif decision == ApprovalDecision.MANUAL_TAKEOVER_REQUIRED:
            self._metrics.manual_takeovers_conducted += 1

        return decision, reason

    def start_intervention(
        self,
        session_id: str,
        operator_id: str,
        before_snapshot_hash: str,
    ) -> str:
        """Initiate recorded human takeover session."""
        return self._evidence_recorder.start_intervention(session_id, operator_id, before_snapshot_hash)

    def record_intervention_event(
        self,
        intervention_id: str,
        event_type: str,
        target_selector: str,
        raw_data: str,
    ) -> InterventionEvent | None:
        """Record sanitized user action during active takeover."""
        return self._evidence_recorder.record_event(intervention_id, event_type, target_selector, raw_data)

    def seal_intervention_bundle(
        self,
        intervention_id: str,
        after_snapshot_hash: str,
    ) -> InterventionEvidenceBundle | None:
        """Seal cryptographic evidence bundle upon conclusion of human takeover."""
        bundle = self._evidence_recorder.seal_evidence_bundle(intervention_id, after_snapshot_hash)
        if bundle is not None:
            self._metrics.evidence_bundles_sealed += 1
        return bundle

    def get_evidence_bundle(self, intervention_id: str) -> InterventionEvidenceBundle | None:
        """Retrieve sealed evidence bundle by intervention ID."""
        return self._evidence_recorder.get_bundle(intervention_id)

    def verify_screen_assertion(
        self,
        probe_id: str,
        expected_selector: str,
        expected_text_contains: str,
        actual_text: str,
        visual_hash_match: bool,
    ) -> ScreenAssertionProbe:
        """Run autonomous DOM and visual snapshot assertion probe."""
        probe = self._assertion_runner.verify_screen_assertion(
            probe_id=probe_id,
            expected_selector=expected_selector,
            expected_text_contains=expected_text_contains,
            actual_text=actual_text,
            visual_hash_match=visual_hash_match,
        )
        if not probe.passed:
            self._metrics.assertion_failures += 1
        return probe
