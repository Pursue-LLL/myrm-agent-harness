"""
[POS] src/myrm_agent_harness/core/security/data_sovereignty_watchdog/sub_intrusive_watchdog.py
[INPUT] time, uuid, typing
[OUTPUT] SubIntrusiveWatchdog

Sub-intrusive value watchdog and anti-annoyance proactive recommendation throttle.
Suppresses trivial noise and emits high-density alert cards only when value or urgency surpasses hard thresholds.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import time
import uuid

from .types import ProactivityValueLevel, SubIntrusiveNotificationCard

logger = logging.getLogger(__name__)


class SubIntrusiveWatchdog:
    """Evaluates background inspection findings and suppresses low-value noise to prevent user notification fatigue."""

    MIN_SAVINGS_THRESHOLD_CENTS: int = 1000  # $10.00
    CRITICAL_DEADLINE_WINDOW_SECONDS: float = 172800.0  # 48 hours
    THROTTLE_COOLDOWN_SECONDS: float = 3600.0  # 1 hour per service

    def __init__(
        self,
        min_savings_cents: int = MIN_SAVINGS_THRESHOLD_CENTS,
        deadline_window_seconds: float = CRITICAL_DEADLINE_WINDOW_SECONDS,
    ) -> None:
        self._min_savings_cents = min_savings_cents
        self._deadline_window_seconds = deadline_window_seconds
        self._cards_registry: list[SubIntrusiveNotificationCard] = []
        self._service_last_emitted: dict[str, float] = {}

    def evaluate_suggestion(
        self,
        title: str,
        service_name: str,
        potential_savings_cents: int,
        deadline_epoch: float | None,
        message: str,
    ) -> SubIntrusiveNotificationCard:
        """Classify suggestion against value and deadline thresholds, suppressing trivial noise."""
        card_id = f"card-{uuid.uuid4().hex[:12]}"
        now = time.time()

        is_critical_deadline = False
        if deadline_epoch is not None:
            time_to_deadline = deadline_epoch - now
            if 0 <= time_to_deadline <= self._deadline_window_seconds:
                is_critical_deadline = True

        is_high_savings = potential_savings_cents >= self._min_savings_cents

        # 1. Determine value level
        if is_critical_deadline:
            value_level = ProactivityValueLevel.CRITICAL_DEADLINE
        elif is_high_savings:
            value_level = ProactivityValueLevel.HIGH_VALUE_ALERT
        elif potential_savings_cents > 0:
            value_level = ProactivityValueLevel.MODERATE_SUGGESTION
        else:
            value_level = ProactivityValueLevel.TRIVIAL_NOISE

        # 2. Determine suppression status
        is_suppressed = False
        if value_level in (ProactivityValueLevel.TRIVIAL_NOISE, ProactivityValueLevel.MODERATE_SUGGESTION):
            # Suppress low value suggestions to keep agent non-annoying
            is_suppressed = True
        else:
            # Check throttling per service
            last_time = self._service_last_emitted.get(service_name, 0.0)
            if now - last_time < self.THROTTLE_COOLDOWN_SECONDS:
                is_suppressed = True
                logger.debug("Throttled duplicate alert for service %s", service_name)
            else:
                self._service_last_emitted[service_name] = now

        card = SubIntrusiveNotificationCard(
            card_id=card_id,
            title=title,
            potential_savings_cents=potential_savings_cents,
            deadline_epoch=deadline_epoch,
            value_level=value_level,
            is_suppressed=is_suppressed,
            message=message,
            service_name=service_name,
        )

        self._cards_registry.append(card)
        logger.info(
            "Watchdog evaluated card %s (level=%s, suppressed=%s) for service %s",
            card_id,
            value_level.value,
            is_suppressed,
            service_name,
        )
        return card

    def list_active_cards(self) -> list[SubIntrusiveNotificationCard]:
        """List high-value alert cards that were not suppressed."""
        return [c for c in self._cards_registry if not c.is_suppressed]

    def list_all_cards(self) -> list[SubIntrusiveNotificationCard]:
        """List all evaluated cards including suppressed noise."""
        return list(self._cards_registry)
