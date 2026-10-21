"""
[INPUT]: Raw delegation events, token usage dictionaries, and auth entitlement tags.
[OUTPUT]: Dual-shape event adapter, subscription cost-saving calculator, and cross-session billing summary.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/delegation_billing/tracker.py
"""

import threading
import time
from typing import Dict, List, Optional
from uuid import uuid4

from .models import (
    DelegationAuthMode,
    DelegationBillingSummary,
    DelegationSourceMetric,
    DelegationUsageRecord,
)

# Standard baseline token cost constants (e.g. Claude 3.5 / GPT-4o tier)
_INPUT_TOKEN_RATE = 0.000003  # $3.00 / 1M tokens
_OUTPUT_TOKEN_RATE = 0.000015  # $15.00 / 1M tokens


class DelegationBillingTracker:
    """Thread-safe tracker and dual-shape adapter for external agent delegation usage and billing divergence."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: List[DelegationUsageRecord] = []

    def record_delegation(
        self,
        session_id: str,
        source: str,
        input_tokens: int,
        output_tokens: int,
        auth_mode: DelegationAuthMode,
        timestamp_ms: Optional[int] = None,
        custom_cost_usd: Optional[float] = None,
    ) -> DelegationUsageRecord:
        """Record an external delegation usage event with transparent dual-track billing breakdown."""
        total_tokens = max(0, input_tokens) + max(0, output_tokens)
        now_ms = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)

        if auth_mode == DelegationAuthMode.SUBSCRIPTION:
            billable = False
            billed_cost = 0.0
            savings = round(
                max(0, input_tokens) * _INPUT_TOKEN_RATE + max(0, output_tokens) * _OUTPUT_TOKEN_RATE, 6
            )
        else:
            billable = True
            savings = 0.0
            if custom_cost_usd is not None:
                billed_cost = round(custom_cost_usd, 6)
            else:
                billed_cost = round(
                    max(0, input_tokens) * _INPUT_TOKEN_RATE + max(0, output_tokens) * _OUTPUT_TOKEN_RATE, 6
                )

        record = DelegationUsageRecord(
            record_id=f"del-{uuid4().hex[:12]}",
            session_id=session_id,
            source=source,
            input_tokens=max(0, input_tokens),
            output_tokens=max(0, output_tokens),
            total_tokens=total_tokens,
            auth_mode=auth_mode,
            billable=billable,
            estimated_savings_usd=savings,
            billed_cost_usd=billed_cost,
            timestamp_ms=now_ms,
        )

        with self._lock:
            self._records.append(record)

        return record

    def adapt_raw_event(
        self, session_id: str, raw_data: Dict[str, object]
    ) -> DelegationUsageRecord:
        """
        Adapt either shape A (nested usage dict) or shape B (flat delegation usage).
        Shape A: {"usage": {"prompt_tokens": 10, "completion_tokens": 20}, "model_name": "claude", "cost_usd": 0.05}
        Shape B: {"source": "delegate:claude", "input_tokens": 10, "output_tokens": 20, "auth_mode": "subscription"}
        """
        source = str(raw_data.get("source") or "delegate:unknown")

        # Extract tokens from either shape
        if "usage" in raw_data and isinstance(raw_data["usage"], dict):
            usage_dict = raw_data["usage"]
            input_tokens = int(usage_dict.get("prompt_tokens") or usage_dict.get("input_tokens") or 0)
            output_tokens = int(usage_dict.get("completion_tokens") or usage_dict.get("output_tokens") or 0)
        else:
            input_tokens = int(raw_data.get("input_tokens") or raw_data.get("prompt_tokens") or 0)
            output_tokens = int(raw_data.get("output_tokens") or raw_data.get("completion_tokens") or 0)

        # Extract auth mode
        auth_mode_raw = str(raw_data.get("auth_mode") or "").lower()
        if auth_mode_raw in ("subscription", "sub"):
            auth_mode = DelegationAuthMode.SUBSCRIPTION
        else:
            auth_mode = DelegationAuthMode.API_KEY

        custom_cost: Optional[float] = None
        if "cost_usd" in raw_data and raw_data["cost_usd"] is not None:
            try:
                custom_cost = float(str(raw_data["cost_usd"]))
            except ValueError:
                custom_cost = None

        return self.record_delegation(
            session_id=session_id,
            source=source,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            auth_mode=auth_mode,
            custom_cost_usd=custom_cost,
        )

    def get_summary(self) -> DelegationBillingSummary:
        """Compute transparent cross-session aggregation of external delegation billing metrics."""
        with self._lock:
            records = list(self._records)

        total_delegations = len(records)
        sub_count = 0
        api_count = 0
        total_sub_tokens = 0
        total_api_tokens = 0
        total_savings = 0.0
        total_billed = 0.0

        source_stats: Dict[str, Dict[str, float]] = {}

        for rec in records:
            if rec.source not in source_stats:
                source_stats[rec.source] = {
                    "calls": 0.0,
                    "sub_tokens": 0.0,
                    "api_tokens": 0.0,
                    "savings_usd": 0.0,
                    "cost_usd": 0.0,
                }
            source_stats[rec.source]["calls"] += 1.0

            if rec.auth_mode == DelegationAuthMode.SUBSCRIPTION:
                sub_count += 1
                total_sub_tokens += rec.total_tokens
                total_savings += rec.estimated_savings_usd
                source_stats[rec.source]["sub_tokens"] += float(rec.total_tokens)
                source_stats[rec.source]["savings_usd"] += rec.estimated_savings_usd
            else:
                api_count += 1
                total_api_tokens += rec.total_tokens
                total_billed += rec.billed_cost_usd
                source_stats[rec.source]["api_tokens"] += float(rec.total_tokens)
                source_stats[rec.source]["cost_usd"] += rec.billed_cost_usd

        sources_list: List[DelegationSourceMetric] = [
            DelegationSourceMetric(
                source=src,
                calls_count=int(metrics["calls"]),
                subscription_tokens=int(metrics["sub_tokens"]),
                api_key_tokens=int(metrics["api_tokens"]),
                savings_usd=round(metrics["savings_usd"], 6),
                cost_usd=round(metrics["cost_usd"], 6),
            )
            for src, metrics in sorted(source_stats.items())
        ]

        return DelegationBillingSummary(
            total_delegations=total_delegations,
            subscription_calls_count=sub_count,
            api_key_calls_count=api_count,
            total_subscription_tokens=total_sub_tokens,
            total_api_key_tokens=total_api_tokens,
            total_estimated_savings_usd=round(total_savings, 6),
            total_billed_cost_usd=round(total_billed, 6),
            sources=sources_list,
            timestamp_ms=int(time.time() * 1000),
        )

    def get_records(self, session_id: Optional[str] = None) -> List[DelegationUsageRecord]:
        """Return audit records, optionally filtered by session ID."""
        with self._lock:
            if session_id is None:
                return list(self._records)
            return [r for r in self._records if r.session_id == session_id]

    def reset(self) -> None:
        """Reset internal buffer for test isolation."""
        with self._lock:
            self._records.clear()
