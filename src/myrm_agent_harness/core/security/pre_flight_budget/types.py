"""Types and data structures for Live Pre-Flight Budget Chokepoint Suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class BudgetAction(StrEnum):
    """Normalized budget enforcement action."""

    PAUSE = "pause"
    STOP = "stop"


class BudgetPeriod(StrEnum):
    """Budget calculation time window."""

    DAILY = "daily"
    SESSION = "session"
    TOTAL = "total"


@dataclass(frozen=True)
class BudgetConfig:
    """Live project budget configuration.

    Always resolved fresh on every evaluation, never snapshotted at session start.
    """

    project_id: str
    limit_amount: float
    currency: str = "USD"
    period: BudgetPeriod = BudgetPeriod.DAILY
    action: BudgetAction = BudgetAction.PAUSE
    anchor_timestamp: float | None = None


@dataclass(frozen=True)
class SpendRecord:
    """Individual spend record item."""

    project_id: str
    amount: float
    currency: str = "USD"
    model_name: str = "default-model"
    source: str = "management"
    timestamp: float = field(
        default_factory=lambda: datetime.now(UTC).timestamp()
    )


@dataclass(frozen=True)
class BudgetDecision:
    """Single enforcement point decision result."""

    tripped: bool
    action: BudgetAction
    project_id: str
    current_spend: float
    limit: float
    currency: str
    period: BudgetPeriod
    reason: str | None = None


class BudgetExceededViolationError(Exception):
    """Hard gate violation error thrown when budget is breached."""

    def __init__(self, decision: BudgetDecision) -> None:
        self.decision = decision
        super().__init__(
            f"Pre-flight budget breached for project {decision.project_id}: "
            f"spend {decision.current_spend:.4f} >= limit {decision.limit:.4f} "
            f"{decision.currency} [action={decision.action.value}, window={decision.period.value}]"
        )


class BudgetEventType(StrEnum):
    """Broadcast event category for the live budget bus."""

    SPEND_RECORDED = "spend_recorded"
    CONFIG_UPDATED = "config_updated"
    CHOKEPOINT_TRIPPED = "chokepoint_tripped"
    QUEUE_LOCKED = "queue_locked"
    QUEUE_UNLOCKED = "queue_unlocked"


@dataclass(frozen=True)
class BudgetBroadcastEvent:
    """Structured event broadcast across system components."""

    event_type: BudgetEventType
    project_id: str
    timestamp: float
    payload: dict[str, str | float | bool]
