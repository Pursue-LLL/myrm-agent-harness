"""Type definitions for Autonomous Bot Budget Guardrail and Token Ceiling Circuit Breaker."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BudgetSandboxMode(StrEnum):
    """Isolation mode for autonomous bot budget sandboxes."""

    ISOLATED_SANDBOX = "ISOLATED_SANDBOX"  # Strictly partitioned pool, stops immediately when exhausted
    CORE_PROTECTED = "CORE_PROTECTED"  # Main user session has guaranteed reserve, bot strictly throttled


class CircuitBreakerState(StrEnum):
    """Tripped state of token ceiling watchdog."""

    CLOSED = "CLOSED"  # Healthy execution, within normal consumption limits
    HALF_OPEN = "HALF_OPEN"  # Warning threshold reached (>= 80%), soft alerts triggered
    OPEN_FROZEN = "OPEN_FROZEN"  # Hard ceiling breached (>= 100%), execution frozen to prevent runaways


@dataclass(slots=True)
class BotBudgetQuota:
    """Configured quota and live watermeter for an autonomous bot."""

    bot_id: str
    bot_name: str
    sandbox_mode: BudgetSandboxMode
    token_ceiling: int
    cost_ceiling_usd: float
    used_tokens: int = 0
    used_cost_usd: float = 0.0
    warning_threshold: float = 0.8
    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    frozen_at: float | None = None
    last_updated_at: float = 0.0


@dataclass(slots=True, frozen=True)
class BudgetConsumeResult:
    """Outcome of attempting to consume tokens or cost against a budget sandbox."""

    allowed: bool
    bot_id: str
    state: CircuitBreakerState
    current_used_tokens: int
    current_used_cost_usd: float
    tokens_remaining: int
    cost_remaining_usd: float
    rejection_reason: str | None = None
