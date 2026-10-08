"""Pre-Flight Budget Chokepoint: THE single enforcement point for LLM API invocations."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from .broadcast_bus import BudgetBroadcastBus
from .live_resolver import LiveBudgetStore
from .types import (
    BudgetAction,
    BudgetBroadcastEvent,
    BudgetDecision,
    BudgetEventType,
    BudgetExceededViolationError,
    BudgetPeriod,
    SpendRecord,
)

logger = logging.getLogger(__name__)


class PreFlightBudgetChokepoint:
    """THE single enforcement point for AI agent LLM invocations and queue dispatching.

    Contracts:
    1. Live resolution: Always resolves the current project budget configuration fresh
       on every single evaluation; never uses session-start snapshots.
    2. Single enforcement point: Exactly one place in the codebase determines
       whether a project is over budget.
    3. Zero penetration: Hard fail-closed stop before physical network packets are sent.
    """

    def __init__(
        self,
        store: LiveBudgetStore | None = None,
        bus: BudgetBroadcastBus | None = None,
    ) -> None:
        self.store = store or LiveBudgetStore()
        self.bus = bus or BudgetBroadcastBus()

    def evaluate(self, project_id: str) -> BudgetDecision:
        """Evaluate whether project_id is over budget right now.

        Pure calculation; takes no trip or mutation action.
        """
        cfg = self.store.get_config(project_id)
        if cfg is None or cfg.limit_amount <= 0:
            return BudgetDecision(
                tripped=False,
                action=BudgetAction.PAUSE,
                project_id=project_id,
                current_spend=0.0,
                limit=0.0,
                currency="USD",
                period=BudgetPeriod.DAILY,
                reason="No active budget limit configured",
            )

        spend = self.store.compute_current_spend(
            project_id=project_id,
            period=cfg.period,
            anchor_timestamp=cfg.anchor_timestamp,
        )

        tripped = spend >= cfg.limit_amount
        reason = (
            f"Spend ({spend:.4f} {cfg.currency}) exceeded or reached limit "
            f"({cfg.limit_amount:.4f} {cfg.currency})"
            if tripped
            else "Spend within budget limit"
        )

        return BudgetDecision(
            tripped=tripped,
            action=cfg.action,
            project_id=project_id,
            current_spend=spend,
            limit=cfg.limit_amount,
            currency=cfg.currency,
            period=cfg.period,
            reason=reason,
        )

    def enforce_pre_flight(self, project_id: str) -> BudgetDecision:
        """Enforce the pre-flight budget chokepoint before making an LLM API call.

        Raises:
            BudgetExceededViolationError: When current spend meets or exceeds the limit.
        """
        decision = self.evaluate(project_id)
        if decision.tripped:
            logger.warning(
                "PreFlightBudgetChokepoint tripped for project=%s: spend=%.4f limit=%.4f",
                project_id,
                decision.current_spend,
                decision.limit,
            )
            event = BudgetBroadcastEvent(
                event_type=BudgetEventType.CHOKEPOINT_TRIPPED,
                project_id=project_id,
                timestamp=datetime.now(UTC).timestamp(),
                payload={
                    "current_spend": decision.current_spend,
                    "limit": decision.limit,
                    "currency": decision.currency,
                    "action": decision.action.value,
                    "period": decision.period.value,
                    "tripped": True,
                },
            )
            self.bus.publish(event)
            raise BudgetExceededViolationError(decision)

        return decision

    def is_queue_dispatch_allowed(self, project_id: str) -> bool:
        """Check whether task queue dispatcher is permitted to dispatch sub-tasks."""
        decision = self.evaluate(project_id)
        if decision.tripped:
            event = BudgetBroadcastEvent(
                event_type=BudgetEventType.QUEUE_LOCKED,
                project_id=project_id,
                timestamp=datetime.now(UTC).timestamp(),
                payload={
                    "current_spend": decision.current_spend,
                    "limit": decision.limit,
                    "action": decision.action.value,
                    "queue_locked": True,
                },
            )
            self.bus.publish(event)
            return False
        return True

    def record_spend(
        self,
        project_id: str,
        amount: float,
        currency: str = "USD",
        model_name: str = "default-model",
        source: str = "management",
    ) -> SpendRecord:
        """Record an LLM call spend and broadcast the update event."""
        record = self.store.record_spend(
            project_id=project_id,
            amount=amount,
            currency=currency,
            model_name=model_name,
            source=source,
        )
        event = BudgetBroadcastEvent(
            event_type=BudgetEventType.SPEND_RECORDED,
            project_id=project_id,
            timestamp=record.timestamp,
            payload={
                "amount": record.amount,
                "currency": record.currency,
                "model_name": record.model_name,
                "source": record.source,
            },
        )
        self.bus.publish(event)
        return record
