"""
[INPUT]: Raw model execution telemetry, auxiliary task identifiers, and provider usage reports.
[OUTPUT]: CanonicalUsageLedgerManager preventing pseudo-free zero-token representations on aborted auxiliary calls.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/aborted_usage_ledger/ledger.py
"""

import threading
import time
from typing import Dict, List, Optional
from uuid import uuid4

from .models import (
    AbortedUsageUnknownStats,
    AuxiliaryCallKind,
    CanonicalUsageLedgerRow,
    LedgerCallStatus,
    UsageAvailabilityKind,
)


class CanonicalUsageLedgerManager:
    """Thread-safe ledger manager enforcing usage-unknown classification on aborted auxiliary model calls."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: List[CanonicalUsageLedgerRow] = []

    def record_call(
        self,
        session_id: str,
        task_id: str,
        call_kind: AuxiliaryCallKind = AuxiliaryCallKind.PRIMARY,
        call_status: LedgerCallStatus = LedgerCallStatus.COMPLETED,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        cost_usd: Optional[float] = None,
        provider_raw_status: str = "",
        timestamp_ms: Optional[int] = None,
    ) -> CanonicalUsageLedgerRow:
        """Record model invocation row. Aborted calls without tokens are strictly recorded as usage-unknown, never 0."""
        with self._lock:
            # First principle: if aborted/cancelled/failed and tokens are absent, mark usage-unknown
            is_aborted_or_failed = call_status in (
                LedgerCallStatus.ABORTED,
                LedgerCallStatus.CANCELLED,
                LedgerCallStatus.FAILED,
            )

            has_valid_tokens = (
                prompt_tokens is not None
                or completion_tokens is not None
                or total_tokens is not None
            )

            if is_aborted_or_failed and not has_valid_tokens:
                availability = UsageAvailabilityKind.USAGE_UNKNOWN
                p_tokens: Optional[int] = None
                c_tokens: Optional[int] = None
                t_tokens: Optional[int] = None
                c_usd: Optional[float] = None
            else:
                availability = UsageAvailabilityKind.EXACT
                p_tokens = max(0, prompt_tokens) if prompt_tokens is not None else 0
                c_tokens = max(0, completion_tokens) if completion_tokens is not None else 0
                t_tokens = total_tokens if total_tokens is not None else (p_tokens + c_tokens)
                c_usd = max(0.0, float(cost_usd)) if cost_usd is not None else 0.0

            row = CanonicalUsageLedgerRow(
                call_id=f"call-{uuid4().hex[:12]}",
                session_id=session_id,
                task_id=task_id,
                call_kind=call_kind,
                call_status=call_status,
                usage_availability=availability,
                prompt_tokens=p_tokens,
                completion_tokens=c_tokens,
                total_tokens=t_tokens,
                cost_usd=c_usd,
                provider_raw_status=provider_raw_status,
                timestamp_ms=timestamp_ms if timestamp_ms is not None else int(time.time() * 1000),
            )
            self._rows.append(row)
            return row

    def get_rows(
        self,
        session_id: Optional[str] = None,
        call_kind: Optional[AuxiliaryCallKind] = None,
        usage_availability: Optional[UsageAvailabilityKind] = None,
        call_status: Optional[LedgerCallStatus] = None,
    ) -> List[CanonicalUsageLedgerRow]:
        """Retrieve recorded ledger rows with optional granular filtering."""
        with self._lock:
            rows = list(self._rows)

        filtered = rows
        if session_id:
            filtered = [r for r in filtered if r.session_id == session_id]
        if call_kind:
            filtered = [r for r in filtered if r.call_kind == call_kind]
        if usage_availability:
            filtered = [r for r in filtered if r.usage_availability == usage_availability]
        if call_status:
            filtered = [r for r in filtered if r.call_status == call_status]

        return filtered

    def get_stats(self, session_id: Optional[str] = None) -> AbortedUsageUnknownStats:
        """Compute transparent aggregation isolating known consumption from unbilled unknown aborted calls."""
        rows = self.get_rows(session_id=session_id)

        total_calls = len(rows)
        unknown_calls = [r for r in rows if r.usage_availability == UsageAvailabilityKind.USAGE_UNKNOWN]
        known_calls = [r for r in rows if r.usage_availability == UsageAvailabilityKind.EXACT]
        aborted_calls = [r for r in rows if r.call_status == LedgerCallStatus.ABORTED]

        known_prompt = sum(r.prompt_tokens for r in known_calls if r.prompt_tokens is not None)
        known_completion = sum(r.completion_tokens for r in known_calls if r.completion_tokens is not None)
        known_total = sum(r.total_tokens for r in known_calls if r.total_tokens is not None)
        known_cost = sum(r.cost_usd for r in known_calls if r.cost_usd is not None)

        return AbortedUsageUnknownStats(
            total_calls=total_calls,
            known_usage_calls=len(known_calls),
            unknown_usage_calls=len(unknown_calls),
            aborted_calls_count=len(aborted_calls),
            total_known_prompt_tokens=known_prompt,
            total_known_completion_tokens=known_completion,
            total_known_tokens=known_total,
            total_known_cost_usd=round(known_cost, 6),
            unknown_risk_flag=len(unknown_calls) > 0,
            timestamp_ms=int(time.time() * 1000),
        )

    def reset(self) -> None:
        """Clear all ledger rows for test isolation."""
        with self._lock:
            self._rows.clear()
