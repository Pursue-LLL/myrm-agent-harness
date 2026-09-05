"""Multi-dimensional budget guard for LLM cost management.

[INPUT]
- .budget_guard::BudgetChecker (POS: Budget guard protocol)
- .budget_guard::BudgetStatus (POS: Budget status enum)

[OUTPUT]
- BudgetDimension: Configuration for a single budget dimension.
- MultidimensionalBudgetGuard: Multi-dimensional budget guard with finalization reserve.

[POS]
Multi-dimensional budget guard. Supports per-session, daily, and per-call limits with
three-level progressive response (NORMAL → WARNING → FINALIZATION → EXCEEDED).
Thread-safe for concurrent agent execution within a single process.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from .budget_guard import BudgetStatus

logger = logging.getLogger(__name__)

BudgetCallback = Callable[[float, float, str], None]


@dataclass(frozen=True)
class BudgetDimension:
    """Configuration for a single budget dimension.

    Args:
        limit_usd: Maximum spend in USD for this dimension.
        warning_threshold: Fraction (0-1) at which WARNING is triggered.
    """

    limit_usd: float
    warning_threshold: float = 0.8


class MultidimensionalBudgetGuard:
    """Multi-dimensional budget guard implementing BudgetChecker protocol.

    Supports three budget dimensions:
      - per_session: Reset each conversation via reset_session()
      - daily: Auto-resets at midnight
      - per_call: Checked per individual LLM call (stateless)

    Three-level progressive response:
      - OK → WARNING → FINALIZATION → EXCEEDED

    FINALIZATION is triggered when remaining budget drops below
    finalization_reserve_pct of the active session or daily limit,
    signaling the agent should output final results immediately.

    Thread-safe: all state mutations protected by a Lock.
    """

    def __init__(
        self,
        *,
        per_session: BudgetDimension | None = None,
        daily: BudgetDimension | None = None,
        per_call: BudgetDimension | None = None,
        finalization_reserve_pct: float = 0.15,
        on_warning: BudgetCallback | None = None,
        on_finalization: BudgetCallback | None = None,
        on_exceeded: BudgetCallback | None = None,
        on_update: BudgetCallback | None = None,
        initial_daily_cost: float = 0.0,
    ) -> None:
        self._per_session = per_session
        self._daily = daily
        self._per_call = per_call
        self._finalization_reserve_pct = finalization_reserve_pct

        self._on_warning = on_warning
        self._on_finalization = on_finalization
        self._on_exceeded = on_exceeded
        self._on_update = on_update

        self._session_cost: float = 0.0
        self._session_costs: dict[str, float] = {}
        self._daily_cost: float = initial_daily_cost
        self._current_date: date = date.today()
        self._last_call_cost: float = 0.0

        self._lock = threading.Lock()
        self._warning_emitted_session = False
        self._finalization_emitted_session = False
        self._warning_emitted_sessions: set[str] = set()
        self._finalization_emitted_sessions: set[str] = set()

    def _maybe_reset_day(self) -> None:
        """Reset daily counter on date change. Must be called under lock."""
        today = date.today()
        if today != self._current_date:
            logger.info(
                "Budget day reset: %s -> %s (yesterday cost: $%.4f)",
                self._current_date,
                today,
                self._daily_cost,
            )
            self._daily_cost = 0.0
            self._current_date = today

    def reset_session(self, session_id: str | None = None) -> None:
        """Reset session cost counter.

        If session_id is provided, resets only that session's counter.
        If session_id is None, clears all tracked sessions and fallback counter.
        """
        with self._lock:
            if session_id is not None:
                self._session_costs[session_id] = 0.0
                self._warning_emitted_sessions.discard(session_id)
                self._finalization_emitted_sessions.discard(session_id)
            else:
                self._session_cost = 0.0
                self._session_costs.clear()
                self._warning_emitted_session = False
                self._finalization_emitted_session = False
                self._warning_emitted_sessions.clear()
                self._finalization_emitted_sessions.clear()

    def _evaluate_status(
        self,
        session_cost: float,
        daily_cost: float,
        call_cost: float,
    ) -> BudgetStatus:
        """Evaluate the strictest budget status across all enabled dimensions."""
        statuses: list[BudgetStatus] = []

        if self._per_call is not None and call_cost > 0:
            if call_cost >= self._per_call.limit_usd:
                statuses.append(BudgetStatus.EXCEEDED)
            elif call_cost >= self._per_call.limit_usd * self._per_call.warning_threshold:
                statuses.append(BudgetStatus.WARNING)

        if self._per_session is not None:
            limit = self._per_session.limit_usd
            finalization_threshold = limit * (1.0 - self._finalization_reserve_pct)
            warning_threshold = limit * self._per_session.warning_threshold

            if session_cost >= limit:
                statuses.append(BudgetStatus.EXCEEDED)
            elif session_cost >= finalization_threshold:
                statuses.append(BudgetStatus.FINALIZATION)
            elif session_cost >= warning_threshold:
                statuses.append(BudgetStatus.WARNING)

        if self._daily is not None:
            limit = self._daily.limit_usd
            finalization_threshold = limit * (1.0 - self._finalization_reserve_pct)
            warning_threshold = limit * self._daily.warning_threshold

            if daily_cost >= limit:
                statuses.append(BudgetStatus.EXCEEDED)
            elif daily_cost >= finalization_threshold:
                statuses.append(BudgetStatus.FINALIZATION)
            elif daily_cost >= warning_threshold:
                statuses.append(BudgetStatus.WARNING)

        if not statuses:
            return BudgetStatus.OK

        severity_order = [BudgetStatus.EXCEEDED, BudgetStatus.FINALIZATION, BudgetStatus.WARNING]
        for s in severity_order:
            if s in statuses:
                return s
        return BudgetStatus.OK

    def check_budget(self, cost: float = 0.0, session_id: str | None = None) -> BudgetStatus:
        """Check budget status without modifying state."""
        with self._lock:
            self._maybe_reset_day()
            target_session_cost = self._session_costs.get(session_id, 0.0) if session_id is not None else self._session_cost
            return self._evaluate_status(
                target_session_cost + cost,
                self._daily_cost + cost,
                cost,
            )

    def record_cost(self, cost: float, session_id: str | None = None) -> BudgetStatus:
        """Record cost and return the new budget status. Triggers callbacks outside lock."""
        pending_callback: tuple[BudgetCallback, float, float, str] | None = None
        pending_update_callback: tuple[BudgetCallback, float, float, str] | None = None

        with self._lock:
            self._maybe_reset_day()
            if session_id is not None:
                self._session_costs[session_id] = self._session_costs.get(session_id, 0.0) + cost
                active_session_cost = self._session_costs[session_id]
            else:
                self._session_cost += cost
                active_session_cost = self._session_cost

            self._daily_cost += cost
            self._last_call_cost = cost

            status = self._evaluate_status(
                active_session_cost,
                self._daily_cost,
                cost,
            )

            if self._on_update:
                pending_update_callback = (self._on_update, active_session_cost, self._get_active_limit(), "unknown")

            if status == BudgetStatus.EXCEEDED:
                dim = self._identify_exceeded_dimension(active_session_cost)
                logger.warning(
                    "Budget EXCEEDED [%s]: session=$%.4f, daily=$%.4f, call=$%.4f",
                    dim,
                    active_session_cost,
                    self._daily_cost,
                    cost,
                )
                if self._on_exceeded:
                    pending_callback = (self._on_exceeded, active_session_cost, self._get_active_limit(), dim)

            elif status == BudgetStatus.FINALIZATION:
                already_emitted = (
                    session_id in self._finalization_emitted_sessions
                    if session_id is not None
                    else self._finalization_emitted_session
                )
                if not already_emitted:
                    if session_id is not None:
                        self._finalization_emitted_sessions.add(session_id)
                    else:
                        self._finalization_emitted_session = True

                    dim = self._identify_finalization_dimension(active_session_cost)
                    logger.warning(
                        "Budget FINALIZATION [%s]: session=$%.4f, daily=$%.4f",
                        dim,
                        active_session_cost,
                        self._daily_cost,
                    )
                    if self._on_finalization:
                        pending_callback = (self._on_finalization, active_session_cost, self._get_active_limit(), dim)

            elif status == BudgetStatus.WARNING:
                already_emitted = (
                    session_id in self._warning_emitted_sessions
                    if session_id is not None
                    else self._warning_emitted_session
                )
                if not already_emitted:
                    if session_id is not None:
                        self._warning_emitted_sessions.add(session_id)
                    else:
                        self._warning_emitted_session = True

                    dim = self._identify_warning_dimension(active_session_cost)
                    logger.warning(
                        "Budget WARNING [%s]: session=$%.4f, daily=$%.4f",
                        dim,
                        active_session_cost,
                        self._daily_cost,
                    )
                    if self._on_warning:
                        pending_callback = (self._on_warning, active_session_cost, self._get_active_limit(), dim)

        if pending_callback is not None:
            cb, cb_cost, cb_limit, cb_dim = pending_callback
            cb(cb_cost, cb_limit, cb_dim)

        if pending_update_callback is not None:
            cb, cb_cost, cb_limit, cb_dim = pending_update_callback
            cb(cb_cost, cb_limit, cb_dim)

        return status

    def get_remaining_budget(self, session_id: str | None = None) -> float | None:
        """Return the minimum remaining budget across all enabled dimensions."""
        with self._lock:
            self._maybe_reset_day()
            remainders: list[float] = []

            if self._per_session is not None:
                current_session_cost = self._session_costs.get(session_id, 0.0) if session_id is not None else self._session_cost
                remainders.append(max(0.0, self._per_session.limit_usd - current_session_cost))
            if self._daily is not None:
                remainders.append(max(0.0, self._daily.limit_usd - self._daily_cost))

            if not remainders:
                return None
            return min(remainders)

    def _get_active_limit(self) -> float:
        """Return the most constraining active limit."""
        limits: list[float] = []
        if self._per_session is not None:
            limits.append(self._per_session.limit_usd)
        if self._daily is not None:
            limits.append(self._daily.limit_usd)
        return min(limits) if limits else 0.0

    def _identify_exceeded_dimension(self, session_cost: float | None = None) -> str:
        s_cost = session_cost if session_cost is not None else self._session_cost
        if self._per_call is not None and self._last_call_cost >= self._per_call.limit_usd:
            return "per_call"
        if self._per_session is not None and s_cost >= self._per_session.limit_usd:
            return "per_session"
        if self._daily is not None and self._daily_cost >= self._daily.limit_usd:
            return "daily"
        return "unknown"

    def _identify_finalization_dimension(self, session_cost: float | None = None) -> str:
        s_cost = session_cost if session_cost is not None else self._session_cost
        if self._per_session is not None:
            threshold = self._per_session.limit_usd * (1.0 - self._finalization_reserve_pct)
            if s_cost >= threshold:
                return "per_session"
        if self._daily is not None:
            threshold = self._daily.limit_usd * (1.0 - self._finalization_reserve_pct)
            if self._daily_cost >= threshold:
                return "daily"
        return "unknown"

    def _identify_warning_dimension(self, session_cost: float | None = None) -> str:
        s_cost = session_cost if session_cost is not None else self._session_cost
        if self._per_session is not None:
            threshold = self._per_session.limit_usd * self._per_session.warning_threshold
            if s_cost >= threshold:
                return "per_session"
        if self._daily is not None:
            threshold = self._daily.limit_usd * self._daily.warning_threshold
            if self._daily_cost >= threshold:
                return "daily"
        if self._per_call is not None:
            threshold = self._per_call.limit_usd * self._per_call.warning_threshold
            if self._last_call_cost >= threshold:
                return "per_call"
        return "unknown"

    def get_session_cost(self, session_id: str | None = None) -> float:
        """Return the cost for a specific session, or the fallback session cost."""
        with self._lock:
            if session_id is not None:
                return self._session_costs.get(session_id, 0.0)
            return self._session_cost

    @property
    def session_cost(self) -> float:
        with self._lock:
            return self._session_cost

    @property
    def daily_cost(self) -> float:
        with self._lock:
            self._maybe_reset_day()
            return self._daily_cost

    @property
    def per_session_limit(self) -> float | None:
        return self._per_session.limit_usd if self._per_session else None

    @property
    def daily_limit(self) -> float | None:
        return self._daily.limit_usd if self._daily else None
