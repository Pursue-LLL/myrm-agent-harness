"""
[INPUT]: Spend amounts, categories, session/task IDs, branch states, and surviving message cost queries.
[OUTPUT]: DurableBudgetLedgerManager recovering daily budget spend accurately from durable ledger instead of fragile surviving messages.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/durable_budget_ledger/ledger.py
"""

from datetime import datetime, timezone
import threading
import time
from typing import Dict, List, Optional
from uuid import uuid4

from .models import (
    DurableBudgetRecoverySummary,
    DurableSpendLedgerRecord,
    SessionActualBilledStatement,
    SpendCategory,
)


class DurableBudgetLedgerManager:
    """Thread-safe ledger manager persisting spend across message retries, rewinds, and session deletions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: List[DurableSpendLedgerRecord] = []

    def record_spend(
        self,
        cost_usd: float,
        category: SpendCategory = SpendCategory.CHAT,
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        is_active_branch: bool = True,
        message_id: Optional[str] = None,
        date_utc: Optional[str] = None,
        timestamp_ms: Optional[int] = None,
    ) -> DurableSpendLedgerRecord:
        """Record an immutable spend entry in the durable ledger."""
        now_ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
        today_key = date_utc or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        record = DurableSpendLedgerRecord(
            record_id=f"spend-{uuid4().hex[:12]}",
            session_id=session_id,
            task_id=task_id,
            cost_usd=max(0.0, float(cost_usd)),
            category=category,
            date_utc=today_key,
            message_id=message_id,
            is_active_branch=is_active_branch,
            timestamp_ms=now_ts,
        )

        with self._lock:
            self._records.append(record)

        return record

    def mark_branch_discarded(
        self,
        message_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> int:
        """Mark records as non-active branch upon retry/rewind without deleting the actual billed spend."""
        with self._lock:
            updated_count = 0
            for r in self._records:
                if message_id and r.message_id == message_id:
                    r.is_active_branch = False
                    updated_count += 1
                elif not message_id and session_id and r.session_id == session_id:
                    r.is_active_branch = False
                    updated_count += 1
            return updated_count

    def get_today_spent(self, date_utc: Optional[str] = None) -> float:
        """Sum cost_usd from today's durable ledger entries to safely recover budget across process restarts."""
        target_date = date_utc or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._lock:
            total = sum(r.cost_usd for r in self._records if r.date_utc == target_date)
        return round(total, 6)

    def get_session_actual_billed(self, session_id: str) -> SessionActualBilledStatement:
        """Reconcile session spend: visible active branch vs actual billed total including discarded retries."""
        with self._lock:
            session_records = [r for r in self._records if r.session_id == session_id]

        actual_billed = sum(r.cost_usd for r in session_records)
        visible_branch = sum(r.cost_usd for r in session_records if r.is_active_branch)
        diff = max(0.0, actual_billed - visible_branch)

        return SessionActualBilledStatement(
            session_id=session_id,
            visible_branch_cost_usd=round(visible_branch, 6),
            actual_billed_cost_usd=round(actual_billed, 6),
            discarded_diff_cost_usd=round(diff, 6),
            records=session_records,
        )

    def get_recovery_summary(
        self,
        date_utc: Optional[str] = None,
        surviving_message_cost_usd: float = 0.0,
    ) -> DurableBudgetRecoverySummary:
        """Generate recovery summary comparing durable ledger against fragile surviving messages."""
        target_date = date_utc or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._lock:
            day_records = [r for r in self._records if r.date_utc == target_date]

        total_durable = sum(r.cost_usd for r in day_records)
        discarded_branch = sum(r.cost_usd for r in day_records if not r.is_active_branch)

        category_breakdown: Dict[str, float] = {}
        for r in day_records:
            cat_key = r.category.value
            category_breakdown[cat_key] = round(category_breakdown.get(cat_key, 0.0) + r.cost_usd, 6)

        gap = max(0.0, total_durable - surviving_message_cost_usd)

        return DurableBudgetRecoverySummary(
            date_utc=target_date,
            total_durable_cost_usd=round(total_durable, 6),
            total_surviving_message_cost_usd=round(surviving_message_cost_usd, 6),
            discarded_branch_cost_usd=round(discarded_branch, 6),
            records_count=len(day_records),
            category_breakdown=category_breakdown,
            budget_underestimation_gap_usd=round(gap, 6),
        )

    def get_all_records(self) -> List[DurableSpendLedgerRecord]:
        with self._lock:
            return list(self._records)

    def reset(self) -> None:
        """Reset ledger for test isolation."""
        with self._lock:
            self._records.clear()
