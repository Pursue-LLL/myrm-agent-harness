"""Real-time Tokenomics savings tracker and live cost diagnostic engine.

[INPUT]
- threading::Lock (POS: Python 线程锁)
- time::time (POS: 高精度时间戳)
- uuid::uuid4 (POS: 唯一事件 ID)
- tracking.tokenomics_types::ModelPricingTier, SavingsEvent, TokenSavingsHudSummary, DEFAULT_MODEL_PRICING_CATALOG

[OUTPUT]
- TokenomicsSavingsTracker: 线程安全实时 Token 节省与成本治理追踪器
- get_global_tokenomics_tracker: 全局单例追踪器获取函数
"""

from __future__ import annotations

import time
import uuid
from threading import Lock

from .tokenomics_types import (
    DEFAULT_MODEL_PRICING_CATALOG,
    ModelPricingTier,
    SavingsEvent,
    TokenSavingsHudSummary,
)


class TokenomicsSavingsTracker:
    """Thread-safe real-time tracker for token compression savings and monetary ROI."""

    def __init__(
        self,
        custom_catalog: dict[str, ModelPricingTier] | None = None,
        max_history_events: int = 200,
    ) -> None:
        self._pricing_catalog = dict(custom_catalog or DEFAULT_MODEL_PRICING_CATALOG)
        self._max_history = max_history_events
        self._lock = Lock()

        self._total_raw_tokens: int = 0
        self._total_compacted_tokens: int = 0
        self._total_saved_tokens: int = 0
        self._total_cost_saved_usd: float = 0.0
        self._total_cached_tokens: int = 0
        self._operator_breakdown: dict[str, int] = {}
        self._events: list[SavingsEvent] = []

    def resolve_pricing(self, model_name: str) -> ModelPricingTier:
        """Resolve model pricing tier using normalized substring matching (longest pattern first)."""
        normalized = (model_name or "default").lower().strip()
        sorted_keys = sorted(
            [k for k in self._pricing_catalog if k != "default"],
            key=len,
            reverse=True,
        )
        for key in sorted_keys:
            if key in normalized:
                return self._pricing_catalog[key]
        return self._pricing_catalog.get("default", DEFAULT_MODEL_PRICING_CATALOG["default"])

    def record_compaction(
        self,
        operator_name: str,
        raw_tokens: int,
        compacted_tokens: int,
        model_name: str = "default",
        cached_tokens: int = 0,
        details: dict[str, object] | None = None,
    ) -> SavingsEvent:
        """Record a single compaction step and update accumulated tokenomics metrics."""
        saved_tokens = max(0, raw_tokens - compacted_tokens)
        saved_ratio = (saved_tokens / raw_tokens) if raw_tokens > 0 else 0.0

        pricing = self.resolve_pricing(model_name)

        # Baseline savings from input token reduction
        compaction_cost_saved = (saved_tokens / 1_000_000.0) * pricing.input_cost_per_million

        # Bonus delta savings from prompt cache hits
        cache_delta_saved = 0.0
        if cached_tokens > 0 and pricing.input_cost_per_million > pricing.cache_read_cost_per_million:
            cost_diff = pricing.input_cost_per_million - pricing.cache_read_cost_per_million
            cache_delta_saved = (cached_tokens / 1_000_000.0) * cost_diff

        total_event_cost_saved = round(compaction_cost_saved + cache_delta_saved, 6)

        event = SavingsEvent(
            event_id=f"sav-{uuid.uuid4().hex[:8]}",
            timestamp=time.time(),
            operator_name=operator_name,
            raw_tokens=raw_tokens,
            compacted_tokens=compacted_tokens,
            saved_tokens=saved_tokens,
            saved_ratio=round(saved_ratio, 4),
            model_name=model_name,
            estimated_cost_saved_usd=total_event_cost_saved,
            cached_tokens=cached_tokens,
            details=dict(details or {}),
        )

        with self._lock:
            self._total_raw_tokens += raw_tokens
            self._total_compacted_tokens += compacted_tokens
            self._total_saved_tokens += saved_tokens
            self._total_cost_saved_usd += total_event_cost_saved
            self._total_cached_tokens += cached_tokens
            self._operator_breakdown[operator_name] = (
                self._operator_breakdown.get(operator_name, 0) + saved_tokens
            )
            self._events.append(event)
            if len(self._events) > self._max_history:
                self._events.pop(0)

        return event

    def get_hud_summary(self, session_id: str = "") -> TokenSavingsHudSummary:
        """Generate snapshot diagnostic view for WebUI/Desktop HUD rendering."""
        with self._lock:
            raw = self._total_raw_tokens
            compacted = self._total_compacted_tokens
            saved = self._total_saved_tokens
            cost_usd = round(self._total_cost_saved_usd, 4)
            cache_hits = self._total_cached_tokens
            breakdown = dict(self._operator_breakdown)
            events_count = len(self._events)

        pct = (saved / raw * 100.0) if raw > 0 else 0.0
        badge_text = (
            f"🎉 累计节省 {saved:,} Tokens (-{pct:.1f}%) · 约节省 ${cost_usd:.4f}"
            if saved > 0
            else "⚡ 上下文就绪 · 实时 Tokenomics 监控中"
        )

        return TokenSavingsHudSummary(
            session_id=session_id or "default_session",
            total_raw_tokens=raw,
            total_compacted_tokens=compacted,
            total_saved_tokens=saved,
            overall_savings_percentage=round(pct, 2),
            total_cost_saved_usd=cost_usd,
            total_prompt_cache_hits_tokens=cache_hits,
            operator_breakdown=breakdown,
            formatted_hud_badge=badge_text,
            recent_events_count=events_count,
        )

    def reset(self) -> None:
        """Reset all counters and event records."""
        with self._lock:
            self._total_raw_tokens = 0
            self._total_compacted_tokens = 0
            self._total_saved_tokens = 0
            self._total_cost_saved_usd = 0.0
            self._total_cached_tokens = 0
            self._operator_breakdown.clear()
            self._events.clear()


_GLOBAL_TRACKER: TokenomicsSavingsTracker | None = None
_GLOBAL_LOCK = Lock()


def get_global_tokenomics_tracker() -> TokenomicsSavingsTracker:
    """Retrieve process-wide singleton TokenomicsSavingsTracker."""
    global _GLOBAL_TRACKER
    if _GLOBAL_TRACKER is None:
        with _GLOBAL_LOCK:
            if _GLOBAL_TRACKER is None:
                _GLOBAL_TRACKER = TokenomicsSavingsTracker()
    return _GLOBAL_TRACKER
