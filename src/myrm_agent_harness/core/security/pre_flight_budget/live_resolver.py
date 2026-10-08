"""Live resolution and storage for project budgets and spend calculations."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from .types import BudgetAction, BudgetConfig, BudgetPeriod, SpendRecord


class LiveBudgetStore:
    """Thread-safe store for live project budget configs and atomic spend ledgers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._configs: dict[str, BudgetConfig] = {}
        self._ledger: dict[str, list[SpendRecord]] = {}

    def set_config(
        self,
        project_id: str,
        limit_amount: float,
        currency: str = "USD",
        period: BudgetPeriod = BudgetPeriod.DAILY,
        action: BudgetAction = BudgetAction.PAUSE,
        anchor_timestamp: float | None = None,
    ) -> BudgetConfig:
        """Atomically set or update live budget config for a project."""
        config = BudgetConfig(
            project_id=project_id,
            limit_amount=limit_amount,
            currency=currency.upper(),
            period=period,
            action=action,
            anchor_timestamp=anchor_timestamp,
        )
        with self._lock:
            self._configs[project_id] = config
        return config

    def get_config(self, project_id: str) -> BudgetConfig | None:
        """Resolve live budget config for a project.

        Guaranteed fresh live resolution, never a stale snapshot.
        """
        with self._lock:
            return self._configs.get(project_id)

    def record_spend(
        self,
        project_id: str,
        amount: float,
        currency: str = "USD",
        model_name: str = "default-model",
        source: str = "management",
    ) -> SpendRecord:
        """Append a spend record to the project's atomic ledger."""
        record = SpendRecord(
            project_id=project_id,
            amount=amount,
            currency=currency.upper(),
            model_name=model_name,
            source=source,
            timestamp=datetime.now(UTC).timestamp(),
        )
        with self._lock:
            if project_id not in self._ledger:
                self._ledger[project_id] = []
            self._ledger[project_id].append(record)
        return record

    def compute_current_spend(
        self, project_id: str, period: BudgetPeriod, anchor_timestamp: float | None = None
    ) -> float:
        """Compute the total spend for the project within the designated window."""
        with self._lock:
            records = list(self._ledger.get(project_id, []))

        now_utc = datetime.now(UTC)
        start_of_day_ts = datetime(
            now_utc.year, now_utc.month, now_utc.day, tzinfo=UTC
        ).timestamp()

        total = 0.0
        for rec in records:
            if period == BudgetPeriod.DAILY:
                if rec.timestamp >= start_of_day_ts:
                    total += rec.amount
            elif period == BudgetPeriod.TOTAL or period == BudgetPeriod.SESSION:
                if anchor_timestamp is not None:
                    if rec.timestamp >= anchor_timestamp:
                        total += rec.amount
                else:
                    total += rec.amount

        return round(total, 6)

    def clear_project(self, project_id: str) -> None:
        """Clear config and ledger for a specific project."""
        with self._lock:
            self._configs.pop(project_id, None)
            self._ledger.pop(project_id, None)

    def clear_all(self) -> None:
        """Clear all stored configs and ledgers."""
        with self._lock:
            self._configs.clear()
            self._ledger.clear()
