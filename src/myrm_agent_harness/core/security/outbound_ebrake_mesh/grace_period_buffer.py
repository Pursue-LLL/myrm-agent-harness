"""
[POS] src/myrm_agent_harness/core/security/outbound_ebrake_mesh/grace_period_buffer.py
[INPUT] time, uuid, types
[OUTPUT] OutboundGracePeriodBuffer

Visual grace-period cooldown buffer and out-of-band physical emergency brake (E-Brake).
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import time
import uuid

from .types import (
    ActionBufferStatus,
    AudienceRiskTier,
    EBrakeStatus,
    OutboundActionItem,
    OutboundActionType,
    OutboundEBrakeMetrics,
)


class OutboundGracePeriodBuffer:
    """Manages cooldown buffer before irreversible dispatches with zero-lag physical e-brake."""

    DEFAULT_GRACE_PERIOD_SECONDS: float = 10.0
    MIN_GRACE_PERIOD_SECONDS: float = 5.0
    MAX_GRACE_PERIOD_SECONDS: float = 60.0

    def __init__(self, metrics: OutboundEBrakeMetrics | None = None) -> None:
        self._buffer: dict[str, OutboundActionItem] = {}
        self._is_e_brake_active: bool = False
        self._last_e_brake_epoch: float | None = None
        self._last_e_brake_reason: str | None = None
        self._total_e_brake_aborts: int = 0
        self._metrics: OutboundEBrakeMetrics = (
            metrics if metrics is not None else OutboundEBrakeMetrics()
        )

    @property
    def metrics(self) -> OutboundEBrakeMetrics:
        """Operational metrics reference."""
        return self._metrics

    def enqueue_action(
        self,
        task_id: str,
        action_type: OutboundActionType,
        destination_target: str,
        payload_text: str,
        risk_tier: AudienceRiskTier,
        grace_period_seconds: float = DEFAULT_GRACE_PERIOD_SECONDS,
    ) -> OutboundActionItem:
        """Enqueue an outbound action into the grace-period cooldown buffer."""
        now = time.time()
        effective_grace = min(
            max(self.MIN_GRACE_PERIOD_SECONDS, grace_period_seconds),
            self.MAX_GRACE_PERIOD_SECONDS,
        )
        action_id = f"act-{uuid.uuid4().hex[:12]}"
        summary = f"{action_type.value} -> {destination_target} ({len(payload_text)} chars)"

        # If e-brake is currently latched, immediately reject to abort status
        if self._is_e_brake_active:
            aborted_item = OutboundActionItem(
                action_id=action_id,
                task_id=task_id,
                action_type=action_type,
                destination_target=destination_target,
                payload_summary=summary,
                full_payload_text=payload_text,
                risk_tier=risk_tier,
                enqueued_at_epoch=now,
                grace_period_seconds=effective_grace,
                status=ActionBufferStatus.ABORTED_BY_E_BRAKE,
                cancellation_reason="Global E-Brake active",
            )
            self._buffer[action_id] = aborted_item
            return aborted_item

        item = OutboundActionItem(
            action_id=action_id,
            task_id=task_id,
            action_type=action_type,
            destination_target=destination_target,
            payload_summary=summary,
            full_payload_text=payload_text,
            risk_tier=risk_tier,
            enqueued_at_epoch=now,
            grace_period_seconds=effective_grace,
            status=ActionBufferStatus.QUEUED_IN_GRACE_PERIOD,
            cancellation_reason=None,
        )
        self._buffer[action_id] = item
        self._metrics.queued_in_grace_period_total += 1
        return item

    def cancel_action(
        self, action_id: str, reason: str = "User manual cancel"
    ) -> bool:
        """Explicitly cancel a queued action during its grace countdown."""
        item = self._buffer.get(action_id)
        if item is None or item.status != ActionBufferStatus.QUEUED_IN_GRACE_PERIOD:
            return False

        cancelled = OutboundActionItem(
            action_id=item.action_id,
            task_id=item.task_id,
            action_type=item.action_type,
            destination_target=item.destination_target,
            payload_summary=item.payload_summary,
            full_payload_text=item.full_payload_text,
            risk_tier=item.risk_tier,
            enqueued_at_epoch=item.enqueued_at_epoch,
            grace_period_seconds=item.grace_period_seconds,
            status=ActionBufferStatus.CANCELLED_BY_USER,
            cancellation_reason=reason,
        )
        self._buffer[action_id] = cancelled
        self._metrics.cancelled_by_user_total += 1
        return True

    def flush_action(self, action_id: str) -> bool:
        """Bypass remaining grace cooldown and immediately dispatch action."""
        item = self._buffer.get(action_id)
        if item is None or item.status != ActionBufferStatus.QUEUED_IN_GRACE_PERIOD:
            return False

        flushed = OutboundActionItem(
            action_id=item.action_id,
            task_id=item.task_id,
            action_type=item.action_type,
            destination_target=item.destination_target,
            payload_summary=item.payload_summary,
            full_payload_text=item.full_payload_text,
            risk_tier=item.risk_tier,
            enqueued_at_epoch=item.enqueued_at_epoch,
            grace_period_seconds=item.grace_period_seconds,
            status=ActionBufferStatus.DISPATCHED_AFTER_GRACE,
            cancellation_reason=None,
        )
        self._buffer[action_id] = flushed
        self._metrics.dispatched_total += 1
        return True

    def poll_and_dispatch(self) -> list[OutboundActionItem]:
        """Poll and transition items whose grace period has expired."""
        now = time.time()
        dispatched: list[OutboundActionItem] = []

        for action_id, item in list(self._buffer.items()):
            if (
                item.status == ActionBufferStatus.QUEUED_IN_GRACE_PERIOD
                and now >= item.enqueued_at_epoch + item.grace_period_seconds
            ):
                transitioned = OutboundActionItem(
                    action_id=item.action_id,
                    task_id=item.task_id,
                    action_type=item.action_type,
                    destination_target=item.destination_target,
                    payload_summary=item.payload_summary,
                    full_payload_text=item.full_payload_text,
                    risk_tier=item.risk_tier,
                    enqueued_at_epoch=item.enqueued_at_epoch,
                    grace_period_seconds=item.grace_period_seconds,
                    status=ActionBufferStatus.DISPATCHED_AFTER_GRACE,
                    cancellation_reason=None,
                )
                self._buffer[action_id] = transitioned
                self._metrics.dispatched_total += 1
                dispatched.append(transitioned)

        return dispatched

    def trigger_e_brake(
        self, reason: str = "Out-of-band physical emergency stop"
    ) -> int:
        """Trigger emergency brake: instantly abort all queued actions and latch e-brake."""
        now = time.time()
        self._is_e_brake_active = True
        self._last_e_brake_epoch = now
        self._last_e_brake_reason = reason
        self._metrics.e_brake_activations_total += 1

        aborted_count = 0
        for action_id, item in list(self._buffer.items()):
            if item.status == ActionBufferStatus.QUEUED_IN_GRACE_PERIOD:
                aborted = OutboundActionItem(
                    action_id=item.action_id,
                    task_id=item.task_id,
                    action_type=item.action_type,
                    destination_target=item.destination_target,
                    payload_summary=item.payload_summary,
                    full_payload_text=item.full_payload_text,
                    risk_tier=item.risk_tier,
                    enqueued_at_epoch=item.enqueued_at_epoch,
                    grace_period_seconds=item.grace_period_seconds,
                    status=ActionBufferStatus.ABORTED_BY_E_BRAKE,
                    cancellation_reason=reason,
                )
                self._buffer[action_id] = aborted
                aborted_count += 1

        self._total_e_brake_aborts += aborted_count
        return aborted_count

    def reset_e_brake(self) -> bool:
        """Reset emergency brake to permit normal operation."""
        self._is_e_brake_active = False
        return True

    def get_e_brake_status(self) -> EBrakeStatus:
        """Get snapshot of current emergency brake state."""
        return EBrakeStatus(
            is_e_brake_active=self._is_e_brake_active,
            last_triggered_at_epoch=self._last_e_brake_epoch,
            trigger_reason=self._last_e_brake_reason,
            actions_aborted_count=self._total_e_brake_aborts,
        )

    def get_action(self, action_id: str) -> OutboundActionItem | None:
        """Lookup action item by ID."""
        return self._buffer.get(action_id)

    def list_queued_actions(self) -> tuple[OutboundActionItem, ...]:
        """List currently pending actions waiting in cooldown."""
        return tuple(
            item
            for item in self._buffer.values()
            if item.status == ActionBufferStatus.QUEUED_IN_GRACE_PERIOD
        )
