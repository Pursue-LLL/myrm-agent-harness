# [INPUT]: WarmthCountdownMetrics, HeartbeatProbeConfig, HeartbeatProbeDecision, HeartbeatExecutionRecord from warmth_types, CacheWarmthGauge, KeepAliveScheduler, ProviderCacheMatrix
# [OUTPUT]: ContextCacheWarmthGaugeAndHeartbeatKeepAliveSuite
# [POS]: myrm_agent_harness.agent.context_management.cache_warmth_keepalive.cache_warmth_suite
"""Unified facade suite for context cache warmth gauge and heartbeat keep-alive (Item 328).

Orchestrates multi-provider cache specifications, real-time warmth countdown
telemetry, and automated silent keep-alive heartbeat probes.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Final

from myrm_agent_harness.agent.context_management.cache_warmth_keepalive.cache_warmth_gauge import (
    CacheWarmthGauge,
)
from myrm_agent_harness.agent.context_management.cache_warmth_keepalive.keepalive_scheduler import (
    KeepAliveScheduler,
)
from myrm_agent_harness.agent.context_management.cache_warmth_keepalive.provider_cache_matrix import (
    ProviderCacheMatrix,
    calculate_probe_cost,
)
from myrm_agent_harness.agent.context_management.cache_warmth_keepalive.warmth_types import (
    CacheWarmthState,
    HeartbeatExecutionRecord,
    HeartbeatProbeConfig,
    HeartbeatProbeDecision,
    ProviderCacheSpec,
    WarmthCountdownMetrics,
)


class ContextCacheWarmthGaugeAndHeartbeatKeepAliveSuite:
    """Industrial suite providing context cache warmth telemetry and keep-alive governance."""

    def __init__(self, probe_config: HeartbeatProbeConfig | None = None) -> None:
        self._lock = threading.RLock()
        self._gauge: Final[CacheWarmthGauge] = CacheWarmthGauge()
        self._scheduler: Final[KeepAliveScheduler] = KeepAliveScheduler(
            default_config=probe_config
        )
        # session_id -> last_user_activity datetime
        self._user_activity: dict[str, datetime] = {}
        # session_id -> last model name used
        self._session_models: dict[str, str] = {}
        # session_id -> last base url used
        self._session_base_urls: dict[str, str] = {}

    @property
    def gauge(self) -> CacheWarmthGauge:
        """Underlying telemetry gauge engine."""
        return self._gauge

    @property
    def scheduler(self) -> KeepAliveScheduler:
        """Underlying keep-alive scheduler."""
        return self._scheduler

    def record_session_interaction(
        self,
        session_id: str,
        cached_tokens: int,
        model_name: str,
        base_url: str = "",
        is_long_ttl: bool = True,
        is_hit: bool = False,
        is_user_interaction: bool = True,
        now: datetime | None = None,
    ) -> WarmthCountdownMetrics:
        """Record model turn interaction, updating telemetry and resetting human activity."""
        ts = now or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        with self._lock:
            self._session_models[session_id] = model_name
            self._session_base_urls[session_id] = base_url

            if is_user_interaction:
                self._user_activity[session_id] = ts
                self._scheduler.on_user_activity(session_id)
                self._gauge.touch_user_activity(session_id, now=ts)

            metrics = self._gauge.record_renewal(
                session_id=session_id,
                cached_tokens=cached_tokens,
                model_name=model_name,
                base_url=base_url,
                is_long_ttl=is_long_ttl,
                is_hit=is_hit,
                now=ts,
            )
            return metrics

    def get_warmth_metrics(
        self,
        session_id: str,
        now: datetime | None = None,
    ) -> WarmthCountdownMetrics:
        """Get live countdown metrics and warmth state for session."""
        return self._gauge.get_metrics(session_id=session_id, now=now)

    def get_ui_capsule(
        self,
        session_id: str,
        now: datetime | None = None,
    ) -> dict[str, str | float | int | bool]:
        """Produce structured payload ready for WebUI and desktop warmth pill components."""
        metrics = self.get_warmth_metrics(session_id=session_id, now=now)
        return {
            "session_id": metrics.session_id,
            "state": metrics.state.value,
            "badge_text": metrics.badge_text,
            "badge_color": metrics.badge_color,
            "remaining_seconds": metrics.remaining_seconds,
            "warmth_ratio": metrics.warmth_ratio,
            "cached_tokens": metrics.cached_tokens,
            "expires_at_iso": metrics.expires_at_iso,
            "estimated_hit_rate": metrics.estimated_hit_rate,
            "cumulative_tokens_saved": metrics.cumulative_tokens_saved,
            "cumulative_cost_saved_usd": metrics.cumulative_cost_saved_usd,
            "is_keepalive_eligible": metrics.is_keepalive_eligible,
        }

    def evaluate_keepalive_probe(
        self,
        session_id: str,
        now: datetime | None = None,
    ) -> HeartbeatProbeDecision:
        """Evaluate if the session requires an automated 1-token silent keep-alive probe."""
        ts = now or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        with self._lock:
            metrics = self._gauge.get_metrics(session_id=session_id, now=ts)
            last_user_active = self._user_activity.get(session_id, ts)
            spec = self._gauge.get_session_spec(session_id)

            return self._scheduler.evaluate_probe(
                metrics=metrics,
                last_user_active_at=last_user_active,
                spec=spec,
                now=ts,
            )

    def record_probe_executed(
        self,
        session_id: str,
        probe_tokens: int = 1,
        cost_usd: float | None = None,
        now: datetime | None = None,
    ) -> HeartbeatExecutionRecord:
        """Acknowledge probe execution, refreshing gauge countdown and logging audit."""
        ts = now or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        with self._lock:
            spec = self._gauge.get_session_spec(session_id)
            if spec is None:
                model_name = self._session_models.get(session_id, "anthropic/claude-3-7-sonnet")
                base_url = self._session_base_urls.get(session_id, "")
                spec = ProviderCacheMatrix.resolve_spec(model_name, base_url, is_long_ttl=True)

            current_metrics = self._gauge.get_metrics(session_id, now=ts)
            if cost_usd is None:
                cost_usd = calculate_probe_cost(
                    cached_tokens=current_metrics.cached_tokens,
                    spec=spec,
                    probe_tokens=probe_tokens,
                )

            # Refresh gauge TTL with existing cached tokens
            self._gauge.record_renewal(
                session_id=session_id,
                cached_tokens=current_metrics.cached_tokens,
                model_name=self._session_models.get(session_id, "claude-3-7-sonnet"),
                base_url=self._session_base_urls.get(session_id, ""),
                is_long_ttl=True,
                is_hit=True,
                now=ts,
            )

            record = self._scheduler.record_probe_execution(
                session_id=session_id,
                probe_tokens=probe_tokens,
                renewed_ttl_seconds=spec.extended_ttl_seconds,
                estimated_probe_cost_usd=cost_usd,
                now=ts,
            )
            return record

    def touch_user_activity(self, session_id: str, now: datetime | None = None) -> None:
        """Notify suite of direct human interaction."""
        ts = now or datetime.now(timezone.utc)
        with self._lock:
            self._user_activity[session_id] = ts
            self._scheduler.on_user_activity(session_id)
            self._gauge.touch_user_activity(session_id, now=ts)

    def update_probe_config(self, config: HeartbeatProbeConfig) -> None:
        """Update keep-alive probe safety parameters."""
        self._scheduler.update_config(config)

    def reset_session(self, session_id: str) -> None:
        """Reset and clean up all resources for session."""
        with self._lock:
            self._gauge.reset_session(session_id)
            self._scheduler.reset_session(session_id)
            self._user_activity.pop(session_id, None)
            self._session_models.pop(session_id, None)
            self._session_base_urls.pop(session_id, None)
