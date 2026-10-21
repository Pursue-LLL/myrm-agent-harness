"""
[INPUT]: Multi-agent trial cost events, unmetered usage imputation parameters, and budget adjustments.
[OUTPUT]: Cumulative delivery ledgers with dual trial/cumulative tracking, unmetered auditing, and budget gate fuses.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/cumulative_delivery_budget/ledger_manager.py
"""

from datetime import datetime, timezone
import threading
from typing import Dict, List, Optional

from .models import (
    CumulativeDeliveryLedger,
    DeliveryBudgetGate,
    TrialRecord,
    UnknownUsageStatus,
)


class CumulativeDeliveryLedgerManager:
    """
    Manages dual-ledger accounting for complex multi-agent deliveries:
    1. Trial Ledger: Granular audit trail for each sub-agent attempt.
    2. Cumulative Delivery Ledger: Aggregate consumption tracking across the entire lifecycle.
    3. Explicit Unknown Usage Auditing: Conservative imputation for unmetered or interrupted calls.
    4. Hard Budget Gate: 70% soft warning and 100% hard pause circuit breaker.
    """

    def __init__(
        self,
        default_imputed_prompt_tokens: int = 1500,
        default_imputed_completion_tokens: int = 500,
        default_imputed_cost_usd: float = 0.006,
    ) -> None:
        self._lock = threading.Lock()
        self._ledgers: Dict[str, CumulativeDeliveryLedger] = {}
        self._default_imputed_prompt_tokens = default_imputed_prompt_tokens
        self._default_imputed_completion_tokens = default_imputed_completion_tokens
        self._default_imputed_cost_usd = default_imputed_cost_usd

    def create_or_get_ledger(
        self,
        delivery_id: str,
        title: str = "Multi-Agent Delivery Lifecycle",
        budget_tokens_limit: Optional[int] = None,
        budget_cost_limit_usd: Optional[float] = None,
    ) -> CumulativeDeliveryLedger:
        with self._lock:
            if delivery_id in self._ledgers:
                ledger = self._ledgers[delivery_id]
                if budget_tokens_limit is not None:
                    ledger.budget_tokens_limit = budget_tokens_limit
                if budget_cost_limit_usd is not None:
                    ledger.budget_cost_limit_usd = budget_cost_limit_usd
                return ledger

            now_iso = datetime.now(timezone.utc).isoformat()
            ledger = CumulativeDeliveryLedger(
                delivery_id=delivery_id,
                title=title,
                budget_tokens_limit=budget_tokens_limit,
                budget_cost_limit_usd=budget_cost_limit_usd,
                created_at=now_iso,
                updated_at=now_iso,
            )
            self._ledgers[delivery_id] = ledger
            return ledger

    def record_trial(
        self,
        delivery_id: str,
        trial_id: str,
        agent_id: str,
        agent_role: str,
        attempt_index: int,
        step_name: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        latency_ms: float = 0.0,
        is_unmetered: bool = False,
        unmetered_status: UnknownUsageStatus = UnknownUsageStatus.METERED,
        custom_imputed_prompt_tokens: Optional[int] = None,
        custom_imputed_completion_tokens: Optional[int] = None,
        custom_imputed_cost_usd: Optional[float] = None,
        budget_tokens_limit: Optional[int] = None,
        budget_cost_limit_usd: Optional[float] = None,
        status: str = "success",
    ) -> CumulativeDeliveryLedger:
        with self._lock:
            if delivery_id not in self._ledgers:
                now_iso = datetime.now(timezone.utc).isoformat()
                self._ledgers[delivery_id] = CumulativeDeliveryLedger(
                    delivery_id=delivery_id,
                    title="Auto-Created Delivery Run",
                    budget_tokens_limit=budget_tokens_limit,
                    budget_cost_limit_usd=budget_cost_limit_usd,
                    created_at=now_iso,
                    updated_at=now_iso,
                )

            ledger = self._ledgers[delivery_id]
            if budget_tokens_limit is not None and ledger.budget_tokens_limit is None:
                ledger.budget_tokens_limit = budget_tokens_limit
            if budget_cost_limit_usd is not None and ledger.budget_cost_limit_usd is None:
                ledger.budget_cost_limit_usd = budget_cost_limit_usd
            now_iso = datetime.now(timezone.utc).isoformat()

            # Identify implicit unmetered condition (zero tokens returned on error/timeout)
            effective_unmetered = is_unmetered
            effective_status = unmetered_status
            if not effective_unmetered and prompt_tokens == 0 and completion_tokens == 0:
                if status in ("timeout", "network_error", "connection_reset"):
                    effective_unmetered = True
                    effective_status = (
                        UnknownUsageStatus.UNMETERED_TIMEOUT
                        if status == "timeout"
                        else UnknownUsageStatus.UNMETERED_CONNECTION_RESET
                    )

            imputed_prompt = 0
            imputed_completion = 0
            imputed_cost = 0.0

            if effective_unmetered:
                imputed_prompt = (
                    custom_imputed_prompt_tokens
                    if custom_imputed_prompt_tokens is not None
                    else self._default_imputed_prompt_tokens
                )
                imputed_completion = (
                    custom_imputed_completion_tokens
                    if custom_imputed_completion_tokens is not None
                    else self._default_imputed_completion_tokens
                )
                imputed_cost = (
                    custom_imputed_cost_usd
                    if custom_imputed_cost_usd is not None
                    else self._default_imputed_cost_usd
                )

            trial = TrialRecord(
                trial_id=trial_id,
                agent_id=agent_id,
                agent_role=agent_role,
                attempt_index=attempt_index,
                step_name=step_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                is_unmetered=effective_unmetered,
                unmetered_status=effective_status,
                imputed_prompt_tokens=imputed_prompt,
                imputed_completion_tokens=imputed_completion,
                imputed_cost_usd=imputed_cost,
                status=status,
                created_at=now_iso,
            )

            ledger.trials.append(trial)
            self._recalculate_ledger_aggregates(ledger)
            ledger.updated_at = now_iso
            return ledger

    def append_budget(
        self,
        delivery_id: str,
        additional_tokens: int = 0,
        additional_cost_usd: float = 0.0,
        set_budget_tokens_limit: Optional[int] = None,
        set_budget_cost_limit_usd: Optional[float] = None,
        force_unpause: bool = True,
    ) -> CumulativeDeliveryLedger:
        with self._lock:
            if delivery_id not in self._ledgers:
                raise KeyError(f"Delivery ledger not found: {delivery_id}")

            ledger = self._ledgers[delivery_id]

            if set_budget_tokens_limit is not None:
                ledger.budget_tokens_limit = set_budget_tokens_limit
            elif ledger.budget_tokens_limit is not None and additional_tokens > 0:
                ledger.budget_tokens_limit += additional_tokens
            elif ledger.budget_tokens_limit is None and additional_tokens > 0:
                ledger.budget_tokens_limit = ledger.total_effective_tokens + additional_tokens

            if set_budget_cost_limit_usd is not None:
                ledger.budget_cost_limit_usd = round(set_budget_cost_limit_usd, 4)
            elif ledger.budget_cost_limit_usd is not None and additional_cost_usd > 0.0:
                ledger.budget_cost_limit_usd = round(
                    ledger.budget_cost_limit_usd + additional_cost_usd, 4
                )
            elif ledger.budget_cost_limit_usd is None and additional_cost_usd > 0.0:
                ledger.budget_cost_limit_usd = round(
                    ledger.total_effective_cost_usd + additional_cost_usd, 4
                )

            now_iso = datetime.now(timezone.utc).isoformat()
            self._recalculate_ledger_aggregates(ledger)

            if force_unpause and ledger.is_paused:
                ledger.is_paused = False
                ledger.pause_reason = None

            ledger.updated_at = now_iso
            return ledger

    def get_ledger(self, delivery_id: str) -> Optional[CumulativeDeliveryLedger]:
        with self._lock:
            return self._ledgers.get(delivery_id)

    def _recalculate_ledger_aggregates(self, ledger: CumulativeDeliveryLedger) -> None:
        total_m_tokens = 0
        total_i_tokens = 0
        total_m_cost = 0.0
        total_i_cost = 0.0
        unmetered_count = 0

        for t in ledger.trials:
            if t.is_unmetered:
                unmetered_count += 1
                total_i_tokens += t.imputed_prompt_tokens + t.imputed_completion_tokens
                total_i_cost += t.imputed_cost_usd
            else:
                total_m_tokens += t.total_tokens
                total_m_cost += t.cost_usd

        ledger.total_metered_tokens = total_m_tokens
        ledger.total_imputed_tokens = total_i_tokens
        ledger.total_effective_tokens = total_m_tokens + total_i_tokens
        ledger.total_metered_cost_usd = round(total_m_cost, 4)
        ledger.total_imputed_cost_usd = round(total_i_cost, 4)
        ledger.total_effective_cost_usd = round(total_m_cost + total_i_cost, 4)
        ledger.unmetered_trials_count = unmetered_count
        ledger.total_trials_count = len(ledger.trials)

        # Evaluate budget gate
        token_ratio = 0.0
        if ledger.budget_tokens_limit and ledger.budget_tokens_limit > 0:
            token_ratio = ledger.total_effective_tokens / ledger.budget_tokens_limit

        cost_ratio = 0.0
        if ledger.budget_cost_limit_usd and ledger.budget_cost_limit_usd > 0:
            cost_ratio = ledger.total_effective_cost_usd / ledger.budget_cost_limit_usd

        max_ratio = max(token_ratio, cost_ratio)

        if max_ratio >= 1.0:
            ledger.gate_verdict = DeliveryBudgetGate.EXCEEDED_PAUSED_100
            ledger.is_paused = True
            if not ledger.pause_reason:
                ledger.pause_reason = (
                    f"整轮累计用量已达硬预算上限 ({max_ratio * 100:.1f}%)，触发保护性熔断挂起"
                )
        elif max_ratio >= 0.7:
            ledger.gate_verdict = DeliveryBudgetGate.WARNING_70
            if not ledger.is_paused:
                ledger.pause_reason = None
        else:
            ledger.gate_verdict = DeliveryBudgetGate.NORMAL
            if not ledger.is_paused:
                ledger.pause_reason = None
