# [INPUT]: WarmthCountdownMetrics, CacheWarmthState, ProviderCacheSpec from warmth_types, ProviderCacheMatrix
# [OUTPUT]: CacheWarmthGauge, format_duration_human
# [POS]: myrm_agent_harness.agent.context_management.cache_warmth_keepalive.cache_warmth_gauge
"""Telemetry engine and countdown gauge for context cache warmth (Item 328).

Provides real-time warmth lifecycle tracking, remaining TTL calculation,
visual UI badge formatting, and savings estimation.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Final

from myrm_agent_harness.agent.context_management.cache_warmth_keepalive.provider_cache_matrix import (
    ProviderCacheMatrix,
    calculate_cache_savings,
)
from myrm_agent_harness.agent.context_management.cache_warmth_keepalive.warmth_types import (
    CacheWarmthState,
    ProviderCacheSpec,
    WarmthCountdownMetrics,
)


def format_duration_human(seconds: float) -> str:
    """Format duration in seconds into human-friendly Chinese duration string."""
    sec = int(max(0, round(seconds)))
    if sec < 60:
        return f"{sec} 秒"
    minutes = sec // 60
    rem_sec = sec % 60
    if minutes < 60:
        return f"{minutes} 分钟" if rem_sec == 0 else f"{minutes} 分 {rem_sec} 秒"
    hours = minutes // 60
    rem_min = minutes % 60
    return f"{hours} 小时" if rem_min == 0 else f"{hours} 小时 {rem_min} 分钟"


class _SessionWarmthData:
    """Internal mutable tracking state per conversation session."""

    __slots__ = (
        "session_id",
        "last_active_at",
        "last_renewed_at",
        "total_ttl_seconds",
        "cached_tokens",
        "spec",
        "hit_count",
        "cumulative_tokens_saved",
        "cumulative_cost_saved_usd",
    )

    def __init__(
        self,
        session_id: str,
        spec: ProviderCacheSpec,
        initial_tokens: int,
        ttl_seconds: int,
        timestamp: datetime,
    ) -> None:
        self.session_id: Final[str] = session_id
        self.spec: ProviderCacheSpec = spec
        self.cached_tokens: int = initial_tokens
        self.total_ttl_seconds: int = ttl_seconds
        self.last_active_at: datetime = timestamp
        self.last_renewed_at: datetime = timestamp
        self.hit_count: int = 0
        self.cumulative_tokens_saved: int = 0
        self.cumulative_cost_saved_usd: float = 0.0


class CacheWarmthGauge:
    """Telemetry engine computing real-time cache warmth status and metrics."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, _SessionWarmthData] = {}

    def record_renewal(
        self,
        session_id: str,
        cached_tokens: int,
        model_name: str,
        base_url: str = "",
        is_long_ttl: bool = True,
        is_hit: bool = False,
        now: datetime | None = None,
    ) -> WarmthCountdownMetrics:
        """Record or refresh cache activity for a session."""
        ts = now or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        spec = ProviderCacheMatrix.resolve_spec(
            model_name=model_name,
            base_url=base_url,
            is_long_ttl=is_long_ttl,
        )
        effective_ttl = spec.extended_ttl_seconds if is_long_ttl else spec.default_ttl_seconds

        with self._lock:
            data = self._sessions.get(session_id)
            if data is None:
                data = _SessionWarmthData(
                    session_id=session_id,
                    spec=spec,
                    initial_tokens=cached_tokens,
                    ttl_seconds=effective_ttl,
                    timestamp=ts,
                )
                self._sessions[session_id] = data
            else:
                data.spec = spec
                data.cached_tokens = cached_tokens
                data.total_ttl_seconds = effective_ttl
                data.last_active_at = ts
                data.last_renewed_at = ts

            if is_hit and cached_tokens >= spec.min_tokens_for_cache:
                data.hit_count += 1
                tokens_saved, cost_saved = calculate_cache_savings(
                    cached_tokens=cached_tokens,
                    spec=spec,
                    hit_count=1,
                )
                data.cumulative_tokens_saved += tokens_saved
                data.cumulative_cost_saved_usd = round(
                    data.cumulative_cost_saved_usd + cost_saved, 6
                )

        return self.get_metrics(session_id=session_id, now=ts)

    def get_metrics(
        self,
        session_id: str,
        now: datetime | None = None,
    ) -> WarmthCountdownMetrics:
        """Compute live warmth metrics and countdown for the given session."""
        ts = now or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        with self._lock:
            data = self._sessions.get(session_id)
            if data is None:
                # Default cold uninitialized state
                return WarmthCountdownMetrics(
                    session_id=session_id,
                    state=CacheWarmthState.COLD,
                    remaining_seconds=0.0,
                    total_ttl_seconds=3600,
                    warmth_ratio=0.0,
                    cached_tokens=0,
                    expires_at_iso=ts.isoformat(),
                    last_active_at_iso=ts.isoformat(),
                    estimated_hit_rate=0.0,
                    cumulative_tokens_saved=0,
                    cumulative_cost_saved_usd=0.0,
                    badge_text="❄️ 缓存已冷却",
                    badge_color="gray",
                    is_keepalive_eligible=False,
                )

            # Check if cache is below activation threshold
            if data.cached_tokens < data.spec.min_tokens_for_cache:
                return WarmthCountdownMetrics(
                    session_id=session_id,
                    state=CacheWarmthState.DISABLED,
                    remaining_seconds=0.0,
                    total_ttl_seconds=data.total_ttl_seconds,
                    warmth_ratio=0.0,
                    cached_tokens=data.cached_tokens,
                    expires_at_iso=ts.isoformat(),
                    last_active_at_iso=data.last_active_at.isoformat(),
                    estimated_hit_rate=0.0,
                    cumulative_tokens_saved=data.cumulative_tokens_saved,
                    cumulative_cost_saved_usd=data.cumulative_cost_saved_usd,
                    badge_text="⏸️ 缓存未激活（未达门槛）",
                    badge_color="gray",
                    is_keepalive_eligible=False,
                )

            elapsed_seconds = max(0.0, (ts - data.last_renewed_at).total_seconds())
            remaining_seconds = max(0.0, float(data.total_ttl_seconds) - elapsed_seconds)
            warmth_ratio = (
                max(0.0, min(1.0, remaining_seconds / float(data.total_ttl_seconds)))
                if data.total_ttl_seconds > 0
                else 0.0
            )

            expires_at = datetime.fromtimestamp(
                data.last_renewed_at.timestamp() + data.total_ttl_seconds, tz=timezone.utc
            )

            # State transition
            if remaining_seconds <= 0.0:
                state = CacheWarmthState.COLD
                badge_text = "❄️ 缓存已冷却"
                badge_color = "gray"
                is_keepalive_eligible = False
            elif remaining_seconds <= float(data.spec.critical_threshold_seconds):
                state = CacheWarmthState.COOLING_CRITICAL
                badge_text = f"⚠️ 缓存即将冷却（剩余 {format_duration_human(remaining_seconds)}）"
                badge_color = "amber"
                is_keepalive_eligible = data.spec.supports_explicit_keepalive
            else:
                state = CacheWarmthState.WARM
                badge_text = f"🔥 缓存保温中（剩余 {format_duration_human(remaining_seconds)}）"
                badge_color = "green"
                is_keepalive_eligible = False

            estimated_hit_rate = 0.90 if state == CacheWarmthState.WARM else (0.50 if state == CacheWarmthState.COOLING_CRITICAL else 0.0)

            return WarmthCountdownMetrics(
                session_id=session_id,
                state=state,
                remaining_seconds=round(remaining_seconds, 2),
                total_ttl_seconds=data.total_ttl_seconds,
                warmth_ratio=round(warmth_ratio, 4),
                cached_tokens=data.cached_tokens,
                expires_at_iso=expires_at.isoformat(),
                last_active_at_iso=data.last_active_at.isoformat(),
                estimated_hit_rate=estimated_hit_rate,
                cumulative_tokens_saved=data.cumulative_tokens_saved,
                cumulative_cost_saved_usd=data.cumulative_cost_saved_usd,
                badge_text=badge_text,
                badge_color=badge_color,
                is_keepalive_eligible=is_keepalive_eligible,
            )

    def touch_user_activity(
        self,
        session_id: str,
        now: datetime | None = None,
    ) -> None:
        """Mark recent human user interaction to prevent idle heartbeat cutoff."""
        ts = now or datetime.now(timezone.utc)
        with self._lock:
            data = self._sessions.get(session_id)
            if data is not None:
                data.last_active_at = ts

    def reset_session(self, session_id: str) -> None:
        """Evict or reset cache tracking data for a session."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def get_session_spec(self, session_id: str) -> ProviderCacheSpec | None:
        """Return provider cache specification associated with session."""
        with self._lock:
            data = self._sessions.get(session_id)
            return data.spec if data is not None else None
