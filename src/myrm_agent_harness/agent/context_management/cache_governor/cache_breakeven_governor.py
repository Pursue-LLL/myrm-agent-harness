"""Pre-flight economic governor guarding against negative ROI cache write premiums.

[INPUT]
- agent.context_management.cache_governor.cache_governor_types::BreakevenAnalysis, CacheRoiStatus,
  CircuitBreakerDecision, ModelPricingTier, SessionNetRoiLedgerEntry, TaskReuseKind (POS: Types and models for
  cache governor.)

[OUTPUT]
- DynamicPromptCacheBreakevenGovernor: Pre-flight economic governor guarding against negative ROI cache write
  premiums.

[POS]
Pre-flight economic governor guarding against negative ROI cache write premiums.
"""

# ============================================================================
# Dynamic Prompt Cache Breakeven Governor & Negative ROI Circuit Breaker (Item 166)
# Pre-flight economic gating against negative ROI from cache write penalties,
# breakeven calculation, and session-level net cache ROI observability ledger.
# ============================================================================

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Sequence

from .cache_governor_types import (
    BreakevenAnalysis,
    CacheRoiStatus,
    CircuitBreakerDecision,
    ModelPricingTier,
    SessionNetRoiLedgerEntry,
    TaskReuseKind,
)

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Default pricing catalog covering standard models with explicit write premiums
_DEFAULT_PRICING: dict[str, ModelPricingTier] = {
    "claude-3-5-sonnet": ModelPricingTier(
        model_name="claude-3-5-sonnet",
        input_cost_per_token=3e-6,
        cache_write_multiplier=1.25,
        cache_read_multiplier=0.10,
    ),
    "claude-3-opus": ModelPricingTier(
        model_name="claude-3-opus",
        input_cost_per_token=15e-6,
        cache_write_multiplier=1.25,
        cache_read_multiplier=0.10,
    ),
    "claude-3-haiku": ModelPricingTier(
        model_name="claude-3-haiku",
        input_cost_per_token=0.25e-6,
        cache_write_multiplier=1.25,
        cache_read_multiplier=0.10,
    ),
    "qwen-max": ModelPricingTier(
        model_name="qwen-max",
        input_cost_per_token=2e-6,
        cache_write_multiplier=1.00,
        cache_read_multiplier=0.20,
    ),
}

_FALLBACK_PRICING = ModelPricingTier(
    model_name="fallback-default",
    input_cost_per_token=3e-6,
    cache_write_multiplier=1.25,
    cache_read_multiplier=0.10,
)


class DynamicPromptCacheBreakevenGovernor:
    """Pre-flight economic governor guarding against negative ROI cache write premiums."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pricing_catalog: dict[str, ModelPricingTier] = dict(_DEFAULT_PRICING)
        # session_id -> SessionNetRoiLedgerEntry
        self._ledgers: dict[str, SessionNetRoiLedgerEntry] = {}

    def register_model_pricing(self, pricing: ModelPricingTier) -> None:
        """Register custom or dynamically discovered model pricing tier."""
        with self._lock:
            self._pricing_catalog[pricing.model_name.lower()] = pricing

    def resolve_pricing(self, model_name: str) -> ModelPricingTier:
        """Resolve pricing configuration for given model name or return fallback."""
        key = model_name.lower()
        with self._lock:
            for k, p in self._pricing_catalog.items():
                if k in key:
                    return p
            return _FALLBACK_PRICING

    def evaluate_pre_flight_decision(
        self,
        model_name: str,
        task_kind: TaskReuseKind,
        estimated_tokens: int,
        custom_turns: int | None = None,
        session_id: str | None = None,
    ) -> CircuitBreakerDecision:
        """Evaluate pre-flight economic viability and decide whether to suppress cache_control."""
        pricing = self.resolve_pricing(model_name)

        # 1. Forecast expected turn count based on task kind or explicit override
        if custom_turns is not None and custom_turns > 0:
            expected_turns = custom_turns
        else:
            if task_kind == TaskReuseKind.SINGLE_TURN_QA:
                expected_turns = 1
            elif task_kind == TaskReuseKind.ONE_OFF_COMMAND:
                expected_turns = 1
            elif task_kind == TaskReuseKind.MULTI_TURN_ITERATION:
                expected_turns = 5
            elif task_kind == TaskReuseKind.DEEP_WORKFLOW:
                expected_turns = 10
            else:
                expected_turns = 1

        write_mult = pricing.cache_write_multiplier
        read_mult = pricing.cache_read_multiplier

        # 2. Compute mathematical breakeven ratio: (write_mult - 1) / (1 - read_mult)
        if write_mult <= 1.0:
            # Zero write penalty: always economically advantageous
            breakeven_ratio = 0.0
            min_reuse_turns = 1
            roi_factor = (expected_turns) * (1.0 - read_mult)
            roi_status = CacheRoiStatus.NEUTRAL_NO_PREMIUM
            should_suppress = False
            reason = "模型无缓存写入溢价，安全准予注入缓存断点。"
        else:
            denominator = max(0.01, 1.0 - read_mult)
            breakeven_ratio = (write_mult - 1.0) / denominator
            min_reuse_turns = 2  # At least 1 write + 1 read turn required to recoup

            if expected_turns < min_reuse_turns:
                # Single turn only: write penalty incurred with 0 subsequent reads -> Guaranteed loss!
                roi_factor = -(write_mult - 1.0)
                roi_status = CacheRoiStatus.NEGATIVE_SUPPRESSED
                should_suppress = True
                pct_loss = int((write_mult - 1.0) * 100)
                reason = (
                    f"任务预期单轮执行（{expected_turns} 轮），无后续复用。"
                    f"缓存写入溢价达 +{pct_loss}%，事前自适应熔断以避免账单倒贴。"
                )
            else:
                # Multiple turns: read discount recoups and yields positive net ROI
                subsequent_reads = expected_turns - 1
                roi_factor = subsequent_reads * (1.0 - read_mult) - (write_mult - 1.0)
                roi_status = CacheRoiStatus.ROI_POSITIVE
                should_suppress = False
                reason = (
                    f"任务预期多轮复用（{expected_turns} 轮 ≥ {min_reuse_turns} 轮）。"
                    f"预计可对冲 {breakeven_ratio:.1%} 盈亏平衡线并获得净收益。"
                )

        analysis = BreakevenAnalysis(
            breakeven_ratio=round(breakeven_ratio, 4),
            min_reuse_turns=min_reuse_turns,
            expected_turns=expected_turns,
            predicted_net_roi_factor=round(roi_factor, 4),
        )

        decision = CircuitBreakerDecision(
            should_suppress_cache=should_suppress,
            roi_status=roi_status,
            reason=reason,
            analysis=analysis,
            evaluated_at_iso=_utc_now_iso(),
        )

        # If suppressed and session_id provided, record suppression count in ledger
        if should_suppress and session_id:
            with self._lock:
                existing = self._ledgers.get(session_id)
                if existing:
                    self._ledgers[session_id] = SessionNetRoiLedgerEntry(
                        session_id=session_id,
                        total_prompt_tokens=existing.total_prompt_tokens,
                        cached_tokens=existing.cached_tokens,
                        cache_creation_tokens=existing.cache_creation_tokens,
                        gross_savings_usd=existing.gross_savings_usd,
                        write_penalty_usd=existing.write_penalty_usd,
                        net_savings_usd=existing.net_savings_usd,
                        suppressed_events_count=existing.suppressed_events_count + 1,
                        last_updated_iso=_utc_now_iso(),
                    )
                else:
                    self._ledgers[session_id] = SessionNetRoiLedgerEntry(
                        session_id=session_id,
                        total_prompt_tokens=0,
                        cached_tokens=0,
                        cache_creation_tokens=0,
                        gross_savings_usd=0.0,
                        write_penalty_usd=0.0,
                        net_savings_usd=0.0,
                        suppressed_events_count=1,
                        last_updated_iso=_utc_now_iso(),
                    )

        logger.info(
            "Pre-flight Cache Evaluation [%s]: suppress=%s, status=%s, turns=%d",
            model_name,
            should_suppress,
            roi_status.value,
            expected_turns,
        )
        return decision

    def record_session_usage(
        self,
        session_id: str,
        usage: Mapping[str, object],
        model: str,
    ) -> SessionNetRoiLedgerEntry:
        """Accurately record token usage, extract cache savings & write penalties, and update ledger."""
        pricing = self.resolve_pricing(model)
        prompt_tokens = int(usage.get("prompt_tokens") or 0)  # type: ignore[arg-type]

        prompt_details = usage.get("prompt_tokens_details")
        cached_tokens = 0
        cache_creation_tokens = 0

        if isinstance(prompt_details, Mapping):
            cached_val = prompt_details.get("cached_tokens")
            if isinstance(cached_val, (int, float)):
                cached_tokens = int(cached_val)

            creation_val = prompt_details.get("cache_creation_input_tokens")
            if isinstance(creation_val, (int, float)):
                cache_creation_tokens = int(creation_val)

        if not cached_tokens and not cache_creation_tokens:
            fallback_cached = usage.get("cached_tokens")
            if isinstance(fallback_cached, (int, float)):
                cached_tokens = int(fallback_cached)

        # Financial computations
        base_cost = pricing.input_cost_per_token
        savings_per_read_token = base_cost * (1.0 - pricing.cache_read_multiplier)
        write_penalty_per_token = base_cost * max(0.0, pricing.cache_write_multiplier - 1.0)

        turn_gross_savings = cached_tokens * savings_per_read_token
        turn_write_penalty = cache_creation_tokens * write_penalty_per_token
        turn_net_savings = turn_gross_savings - turn_write_penalty

        with self._lock:
            existing = self._ledgers.get(session_id)
            if existing:
                new_entry = SessionNetRoiLedgerEntry(
                    session_id=session_id,
                    total_prompt_tokens=existing.total_prompt_tokens + prompt_tokens,
                    cached_tokens=existing.cached_tokens + cached_tokens,
                    cache_creation_tokens=existing.cache_creation_tokens + cache_creation_tokens,
                    gross_savings_usd=round(existing.gross_savings_usd + turn_gross_savings, 6),
                    write_penalty_usd=round(existing.write_penalty_usd + turn_write_penalty, 6),
                    net_savings_usd=round(existing.net_savings_usd + turn_net_savings, 6),
                    suppressed_events_count=existing.suppressed_events_count,
                    last_updated_iso=_utc_now_iso(),
                )
            else:
                new_entry = SessionNetRoiLedgerEntry(
                    session_id=session_id,
                    total_prompt_tokens=prompt_tokens,
                    cached_tokens=cached_tokens,
                    cache_creation_tokens=cache_creation_tokens,
                    gross_savings_usd=round(turn_gross_savings, 6),
                    write_penalty_usd=round(turn_write_penalty, 6),
                    net_savings_usd=round(turn_net_savings, 6),
                    suppressed_events_count=0,
                    last_updated_iso=_utc_now_iso(),
                )
            self._ledgers[session_id] = new_entry
            return new_entry

    def get_session_ledger(self, session_id: str) -> SessionNetRoiLedgerEntry | None:
        """Fetch accumulated net ROI financial ledger for specific session."""
        with self._lock:
            return self._ledgers.get(session_id)

    def get_global_audit_summary(self) -> dict[str, float | int]:
        """Aggregate global audit metrics across all tracked sessions."""
        with self._lock:
            total_prompt = sum(e.total_prompt_tokens for e in self._ledgers.values())
            total_cached = sum(e.cached_tokens for e in self._ledgers.values())
            total_created = sum(e.cache_creation_tokens for e in self._ledgers.values())
            total_gross = sum(e.gross_savings_usd for e in self._ledgers.values())
            total_penalty = sum(e.write_penalty_usd for e in self._ledgers.values())
            total_net = sum(e.net_savings_usd for e in self._ledgers.values())
            total_suppressed = sum(e.suppressed_events_count for e in self._ledgers.values())

            return {
                "active_sessions_tracked": len(self._ledgers),
                "total_prompt_tokens": total_prompt,
                "total_cached_tokens": total_cached,
                "total_cache_creation_tokens": total_created,
                "total_gross_savings_usd": round(total_gross, 6),
                "total_write_penalty_usd": round(total_penalty, 6),
                "total_net_savings_usd": round(total_net, 6),
                "total_negative_roi_suppressed_count": total_suppressed,
            }
