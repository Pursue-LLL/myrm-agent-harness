"""
[POS] src/myrm_agent_harness/core/security/data_sovereignty_watchdog/facade.py
[INPUT] typing
[OUTPUT] DataSovereigntyWatchdogSuite

Unified facade for Private Sandbox Data Sovereignty & Sub-Intrusive Proactivity Watchdog Suite.
Unifies private volume data sovereignty sealing, anti-annoyance value threshold gating,
and high-stakes action human consent gates.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .high_stakes_consent_gate import HighStakesConsentGate
from .sovereignty_seal import SandboxSovereigntySeal
from .sub_intrusive_watchdog import SubIntrusiveWatchdog
from .types import (
    DataSovereigntyWatchdogMetrics,
    HighStakesActionType,
    HighStakesConsentTicket,
    SovereigntySealLevel,
    SovereigntySealManifest,
    SubIntrusiveNotificationCard,
)

logger = logging.getLogger(__name__)


class DataSovereigntyWatchdogSuite:
    """Unified security facade coordinating data sovereignty seals, sub-intrusive value filtering, and consent gates."""

    def __init__(
        self,
        min_savings_cents: int = SubIntrusiveWatchdog.MIN_SAVINGS_THRESHOLD_CENTS,
        deadline_window_seconds: float = SubIntrusiveWatchdog.CRITICAL_DEADLINE_WINDOW_SECONDS,
    ) -> None:
        self._seal_engine = SandboxSovereigntySeal()
        self._watchdog = SubIntrusiveWatchdog(
            min_savings_cents=min_savings_cents,
            deadline_window_seconds=deadline_window_seconds,
        )
        self._consent_gate = HighStakesConsentGate()
        self._metrics = DataSovereigntyWatchdogMetrics()

    @property
    def metrics(self) -> DataSovereigntyWatchdogMetrics:
        """Cumulative operational metrics."""
        return self._metrics

    def issue_sovereignty_seal(
        self,
        storage_target: str,
        volume_mount_path: str,
        seal_level: SovereigntySealLevel = SovereigntySealLevel.PRIVATE_SANDBOX_VOLUME,
    ) -> SovereigntySealManifest:
        """Issue an immutable data sovereignty seal confirming private volume isolation."""
        self._metrics.sovereignty_seals_issued_total += 1
        return self._seal_engine.issue_seal(
            storage_target=storage_target,
            volume_mount_path=volume_mount_path,
            seal_level=seal_level,
        )

    def verify_sovereignty_seal(self, seal_id: str) -> bool:
        """Verify cryptographic integrity of an issued sovereignty seal."""
        return self._seal_engine.verify_seal(seal_id)

    def get_latest_seal(self) -> SovereigntySealManifest | None:
        """Retrieve most recently issued sovereignty seal."""
        return self._seal_engine.get_latest_seal()

    def evaluate_proactive_suggestion(
        self,
        title: str,
        service_name: str,
        potential_savings_cents: int,
        deadline_epoch: float | None,
        message: str,
    ) -> SubIntrusiveNotificationCard:
        """Evaluate suggestion and suppress trivial noise according to sub-intrusive contract."""
        self._metrics.proactive_scans_total += 1
        card = self._watchdog.evaluate_suggestion(
            title=title,
            service_name=service_name,
            potential_savings_cents=potential_savings_cents,
            deadline_epoch=deadline_epoch,
            message=message,
        )

        if card.is_suppressed:
            self._metrics.noise_suppressed_total += 1
        else:
            self._metrics.high_value_alerts_emitted_total += 1

        return card

    def list_active_notification_cards(self) -> list[SubIntrusiveNotificationCard]:
        """List high-value alert cards that were not suppressed."""
        return self._watchdog.list_active_cards()

    def list_all_notification_cards(self) -> list[SubIntrusiveNotificationCard]:
        """List all evaluated cards including suppressed noise."""
        return self._watchdog.list_all_cards()

    def create_high_stakes_consent(
        self,
        action_type: HighStakesActionType,
        service_name: str,
        financial_impact_cents: int,
        payload_summary: str,
    ) -> HighStakesConsentTicket:
        """Lock high-stakes operation behind a pending consent ticket requiring explicit human click."""
        self._metrics.high_stakes_actions_blocked_total += 1
        return self._consent_gate.create_consent_ticket(
            action_type=action_type,
            service_name=service_name,
            financial_impact_cents=financial_impact_cents,
            payload_summary=payload_summary,
        )

    def approve_consent(self, ticket_id: str) -> HighStakesConsentTicket:
        """Operator explicitly authorizes the high-stakes transaction."""
        self._metrics.high_stakes_consents_approved_total += 1
        return self._consent_gate.approve_ticket(ticket_id)

    def deny_consent(self, ticket_id: str) -> HighStakesConsentTicket:
        """Operator explicitly rejects the high-stakes transaction."""
        self._metrics.high_stakes_consents_denied_total += 1
        return self._consent_gate.deny_ticket(ticket_id)

    def list_pending_consents(self) -> list[HighStakesConsentTicket]:
        """List all operations currently awaiting human consent."""
        return self._consent_gate.list_pending_tickets()
