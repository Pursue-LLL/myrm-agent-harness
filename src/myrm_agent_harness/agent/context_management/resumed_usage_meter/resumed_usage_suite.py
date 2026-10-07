"""Master suite governing resumed session history token exclusion and net run usage metering.

Tracks session resumption watermarks, audits incremental execution costs,
and maintains an auditable double-entry billing ledger across dialogue turns.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence

from .net_run_usage_meter import NetRunUsageMeter
from .resumed_usage_types import (
    NetRunUsage,
    RawTurnUsage,
    ResumptionBaseline,
    SessionUsageSummary,
    UsageBillingLedgerRecord,
)


class ResumedSessionHistoryTokenExclusionAndNetRunUsageMeterSuite:
    """Master suite orchestrating historical context exclusion and net incremental task metering."""

    def __init__(self, meter: NetRunUsageMeter | None = None) -> None:
        self._meter = meter or NetRunUsageMeter()
        self._baselines: dict[str, ResumptionBaseline] = {}
        self._resumed_first_turn_handled: set[str] = set()
        self._ledger: list[UsageBillingLedgerRecord] = []

    @property
    def meter(self) -> NetRunUsageMeter:
        """Access underlying net usage calculation engine."""
        return self._meter

    def register_resumption_baseline(
        self,
        session_id: str,
        historical_tokens: int,
        turn_count: int,
        prior_cost: float = 0.0,
    ) -> ResumptionBaseline:
        """Record the inherited context boundary when a dormant session is re-opened."""
        baseline = ResumptionBaseline(
            session_id=session_id,
            resumed_history_tokens=historical_tokens,
            resumed_turn_count=turn_count,
            resumed_at_iso=datetime.now(timezone.utc).isoformat(),
            prior_cumulative_cost=prior_cost,
        )
        self._baselines[session_id] = baseline
        self._resumed_first_turn_handled.discard(session_id)
        return baseline

    def get_resumption_baseline(self, session_id: str) -> ResumptionBaseline | None:
        """Retrieve the resumption watermark for a given session."""
        return self._baselines.get(session_id)

    def meter_turn_usage(
        self,
        session_id: str,
        raw_usage: RawTurnUsage,
        turn_index: int,
    ) -> UsageBillingLedgerRecord:
        """Audit and meter a turn execution, isolating incremental run usage from pre-existing history."""
        baseline = self._baselines.get(session_id)
        is_first_resumed = (baseline is not None) and (session_id not in self._resumed_first_turn_handled)

        net_usage = self._meter.calculate_net_run_usage(
            raw_usage=raw_usage,
            baseline=baseline,
            is_first_resumed_turn=is_first_resumed,
        )

        if is_first_resumed:
            self._resumed_first_turn_handled.add(session_id)

        cost = self._meter.estimate_cost(net_usage=net_usage, raw_usage=raw_usage)

        record = UsageBillingLedgerRecord(
            record_id=f"rec-{uuid.uuid4().hex[:10]}",
            session_id=session_id,
            turn_index=turn_index,
            is_resumed_turn=is_first_resumed,
            raw_usage=raw_usage,
            net_usage=net_usage,
            computed_cost=cost,
        )

        self._ledger.append(record)
        return record

    def get_session_summary(self, session_id: str) -> SessionUsageSummary:
        """Aggregate total gross vs net usage and billing metrics for a session."""
        records = [r for r in self._ledger if r.session_id == session_id]
        total_gross = sum(r.net_usage.gross_physical_tokens for r in records)
        total_net = sum(r.net_usage.net_billable_tokens for r in records)
        total_excluded = sum(r.net_usage.excluded_history_tokens for r in records)
        total_cost = sum(r.computed_cost for r in records)

        baseline = self._baselines.get(session_id)
        if baseline:
            total_cost += baseline.prior_cumulative_cost

        return SessionUsageSummary(
            session_id=session_id,
            total_turns=len(records),
            lifetime_gross_tokens=total_gross,
            lifetime_net_run_tokens=total_net,
            total_excluded_history_tokens=total_excluded,
            total_cost=round(total_cost, 6),
        )

    def get_global_telemetry(self) -> dict[str, object]:
        """Produce macro-level audit statistics across all metered sessions."""
        total_turns = len(self._ledger)
        total_excluded = sum(r.net_usage.excluded_history_tokens for r in self._ledger)
        total_net = sum(r.net_usage.net_billable_tokens for r in self._ledger)

        return {
            "total_turns_metered": total_turns,
            "total_sessions_resumed": len(self._baselines),
            "total_excluded_history_tokens": total_excluded,
            "total_net_billable_tokens": total_net,
        }
