"""[INPUT] Multi-source token metrics with 6-dimensional composite keys.
[OUTPUT] Thread-safe in-memory and persistent composite usage ledger with dual-track reconciliation.
[POS] myrm_agent_harness.observability.composite_usage_ledger.ledger

Implements the persistent 6-dimensional composite usage ledger:
Primary Key: (session_id, model, billing_provider, billing_base_url, billing_mode, task)
Provides granular task attribution and estimated vs actual cost reconciliation.
"""

from collections import defaultdict
import threading
import time

from .models import (
    CompositeUsageKey,
    CompositeUsageRecord,
    CostReconciliationStatus,
    LedgerSummary,
)


class CompositeSessionModelUsageLedger:
    """Thread-safe composite usage ledger indexing by 6-dimensional primary keys."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # composite_key_string -> CompositeUsageRecord
        self._records: dict[str, CompositeUsageRecord] = {}

    def record_usage(
        self,
        session_id: str,
        model: str,
        billing_provider: str,
        billing_base_url: str,
        billing_mode: str,
        task: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        reasoning_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        actual_cost_usd: float = 0.0,
        timestamp_ms: int | None = None,
    ) -> CompositeUsageRecord:
        """Record or accumulate usage against the 6-dimensional composite key."""
        clean_sid = session_id.strip() or "default_session"
        clean_model = model.strip() or "unknown_model"
        clean_provider = billing_provider.strip() or "default_provider"
        clean_base_url = billing_base_url.strip() or "https://api.openai.com/v1"
        clean_mode = billing_mode.strip() or "standard"
        clean_task = task.strip() or "main_turn"

        key = CompositeUsageKey(
            session_id=clean_sid,
            model=clean_model,
            billing_provider=clean_provider,
            billing_base_url=clean_base_url,
            billing_mode=clean_mode,
            task=clean_task,
        )
        key_str = key.to_key_string()
        now_ms = timestamp_ms or int(time.time() * 1000)

        with self._lock:
            if key_str not in self._records:
                self._records[key_str] = CompositeUsageRecord(
                    key=key,
                    first_seen_ms=now_ms,
                    last_seen_ms=now_ms,
                )

            record = self._records[key_str]
            record.accumulate(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
                reasoning_tokens=reasoning_tokens,
                estimated_cost_usd=estimated_cost_usd,
                actual_cost_usd=actual_cost_usd,
                timestamp_ms=now_ms,
            )
            return record

    def reconcile_invoice(
        self,
        session_id: str,
        model: str,
        billing_provider: str,
        billing_base_url: str,
        billing_mode: str,
        task: str,
        actual_cost_usd: float,
        timestamp_ms: int | None = None,
    ) -> CompositeUsageRecord | None:
        """Update actual billed cost from upstream provider invoice and perform reconciliation."""
        key = CompositeUsageKey(
            session_id=session_id.strip() or "default_session",
            model=model.strip() or "unknown_model",
            billing_provider=billing_provider.strip() or "default_provider",
            billing_base_url=billing_base_url.strip() or "https://api.openai.com/v1",
            billing_mode=billing_mode.strip() or "standard",
            task=task.strip() or "main_turn",
        )
        key_str = key.to_key_string()
        now_ms = timestamp_ms or int(time.time() * 1000)

        with self._lock:
            if key_str not in self._records:
                return None
            record = self._records[key_str]
            record.reconcile_actual(actual_cost_usd=actual_cost_usd, timestamp_ms=now_ms)
            return record

    def get_records(
        self,
        session_id: str | None = None,
        task: str | None = None,
        model: str | None = None,
        limit: int = 100,
    ) -> list[CompositeUsageRecord]:
        """Query matching usage records sorted by last_seen_ms descending."""
        with self._lock:
            results: list[CompositeUsageRecord] = []
            for rec in self._records.values():
                if session_id and rec.key.session_id != session_id.strip():
                    continue
                if task and rec.key.task != task.strip():
                    continue
                if model and rec.key.model != model.strip():
                    continue
                results.append(rec)

            results.sort(key=lambda r: r.last_seen_ms, reverse=True)
            return results[: max(1, limit)]

    def get_summary(self, session_id: str | None = None) -> LedgerSummary:
        """Aggregate ledger metrics across records."""
        with self._lock:
            active_records = [
                rec
                for rec in self._records.values()
                if not session_id or rec.key.session_id == session_id.strip()
            ]

        total_calls = sum(r.api_call_count for r in active_records)
        total_in = sum(r.input_tokens for r in active_records)
        total_out = sum(r.output_tokens for r in active_records)
        total_cache = sum(r.cache_read_tokens + r.cache_write_tokens for r in active_records)
        total_est = sum(r.estimated_cost_usd for r in active_records)
        total_act = sum(r.actual_cost_usd for r in active_records)
        reconciled_cnt = sum(1 for r in active_records if r.cost_status == CostReconciliationStatus.RECONCILED)
        discrepancy_cnt = sum(1 for r in active_records if r.cost_status == CostReconciliationStatus.DISCREPANCY_ALERT)

        task_spend: dict[str, float] = defaultdict(float)
        model_spend: dict[str, float] = defaultdict(float)
        for r in active_records:
            spend = r.actual_cost_usd if r.actual_cost_usd > 0.0 else r.estimated_cost_usd
            task_spend[r.key.task] += round(spend, 6)
            model_spend[r.key.model] += round(spend, 6)

        return LedgerSummary(
            total_records=len(active_records),
            total_calls=total_calls,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            total_cache_tokens=total_cache,
            total_estimated_usd=round(total_est, 6),
            total_actual_usd=round(total_act, 6),
            reconciled_records_count=reconciled_cnt,
            discrepancy_records_count=discrepancy_cnt,
            task_spend_distribution=dict(task_spend),
            model_spend_distribution=dict(model_spend),
        )

    def reset(self, session_id: str | None = None) -> None:
        """Clear ledger entries for a specific session or entirely."""
        with self._lock:
            if session_id:
                sid = session_id.strip()
                keys_to_del = [k for k, r in self._records.items() if r.key.session_id == sid]
                for k in keys_to_del:
                    del self._records[k]
            else:
                self._records.clear()


# Global thread-safe singleton
_default_ledger: CompositeSessionModelUsageLedger | None = None
_ledger_lock = threading.Lock()


def get_default_composite_usage_ledger() -> CompositeSessionModelUsageLedger:
    """Retrieve or initialize the global CompositeSessionModelUsageLedger instance."""
    global _default_ledger
    if _default_ledger is None:
        with _ledger_lock:
            if _default_ledger is None:
                _default_ledger = CompositeSessionModelUsageLedger()
    return _default_ledger
