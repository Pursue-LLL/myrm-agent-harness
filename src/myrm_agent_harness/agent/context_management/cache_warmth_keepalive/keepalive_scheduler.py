# [INPUT]: WarmthCountdownMetrics, HeartbeatProbeConfig, HeartbeatProbeDecision, HeartbeatExecutionRecord, ProviderCacheSpec from warmth_types
# [OUTPUT]: KeepAliveScheduler
# [POS]: myrm_agent_harness.agent.context_management.cache_warmth_keepalive.keepalive_scheduler
"""Keep-alive heartbeat probe scheduler and safety guardrails (Item 328).

Evaluates when to silently dispatch micro 1-token keep-alive probes before cache
expiration, enforcing budgets and human idle cutoff limits.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Final

from myrm_agent_harness.agent.context_management.cache_warmth_keepalive.warmth_types import (
    CacheWarmthState,
    HeartbeatExecutionRecord,
    HeartbeatProbeConfig,
    HeartbeatProbeDecision,
    ProviderCacheSpec,
    WarmthCountdownMetrics,
)


class KeepAliveScheduler:
    """Scheduler for automated silent keep-alive probes with safety thresholds."""

    def __init__(self, default_config: HeartbeatProbeConfig | None = None) -> None:
        self._lock = threading.RLock()
        self._config: HeartbeatProbeConfig = default_config or HeartbeatProbeConfig()
        # session_id -> consecutive heartbeats count
        self._consecutive_heartbeats: dict[str, int] = {}
        # session_id -> execution history list
        self._history: dict[str, list[HeartbeatExecutionRecord]] = {}

    @property
    def config(self) -> HeartbeatProbeConfig:
        """Active configuration for probe governance."""
        with self._lock:
            return self._config

    def update_config(self, config: HeartbeatProbeConfig) -> None:
        """Update global heartbeat probe configuration."""
        with self._lock:
            self._config = config

    def evaluate_probe(
        self,
        metrics: WarmthCountdownMetrics,
        last_user_active_at: datetime,
        spec: ProviderCacheSpec | None,
        now: datetime | None = None,
    ) -> HeartbeatProbeDecision:
        """Evaluate whether a silent keep-alive probe should be dispatched."""
        ts = now or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if last_user_active_at.tzinfo is None:
            last_user_active_at = last_user_active_at.replace(tzinfo=timezone.utc)

        with self._lock:
            cfg = self._config
            session_id = metrics.session_id

            # 1. Check master switch
            if not cfg.enabled:
                return HeartbeatProbeDecision(
                    should_probe=False,
                    reason="Heartbeat keep-alive is globally disabled",
                    session_id=session_id,
                )

            # 2. Check provider capability
            if spec is None or not spec.supports_explicit_keepalive:
                return HeartbeatProbeDecision(
                    should_probe=False,
                    reason="Provider does not support explicit lightweight keep-alive renewal",
                    session_id=session_id,
                )

            # 3. Check token volume threshold
            if metrics.cached_tokens < cfg.min_tokens_threshold:
                return HeartbeatProbeDecision(
                    should_probe=False,
                    reason=f"Cached tokens ({metrics.cached_tokens}) below min keep-alive threshold ({cfg.min_tokens_threshold})",
                    session_id=session_id,
                )

            # 4. Check state: must be in critical cooling window and not completely cold
            if metrics.state == CacheWarmthState.WARM:
                return HeartbeatProbeDecision(
                    should_probe=False,
                    reason=f"Cache is still warm with {metrics.remaining_seconds:.1f}s remaining",
                    session_id=session_id,
                )
            if metrics.state != CacheWarmthState.COOLING_CRITICAL:
                return HeartbeatProbeDecision(
                    should_probe=False,
                    reason=f"Cache is not in critical cooling state (current: {metrics.state.value})",
                    session_id=session_id,
                )

            # 5. Check remaining seconds vs configured critical window
            if metrics.remaining_seconds > float(cfg.critical_window_seconds):
                return HeartbeatProbeDecision(
                    should_probe=False,
                    reason=f"Remaining seconds ({metrics.remaining_seconds:.1f}s) above critical probe window ({cfg.critical_window_seconds}s)",
                    session_id=session_id,
                )

            # 6. Check consecutive heartbeats limit (prevent infinite background burning)
            consecutive = self._consecutive_heartbeats.get(session_id, 0)
            if consecutive >= cfg.max_consecutive_heartbeats:
                return HeartbeatProbeDecision(
                    should_probe=False,
                    reason=f"Max consecutive keep-alive probes reached ({consecutive}/{cfg.max_consecutive_heartbeats}) without user interaction",
                    session_id=session_id,
                )

            # 7. Check user idle cutoff duration
            idle_seconds = max(0.0, (ts - last_user_active_at).total_seconds())
            if idle_seconds > float(cfg.max_idle_seconds):
                return HeartbeatProbeDecision(
                    should_probe=False,
                    reason=f"User idle time ({idle_seconds:.1f}s) exceeded allowed ceiling ({cfg.max_idle_seconds}s)",
                    session_id=session_id,
                )

            # Approved
            return HeartbeatProbeDecision(
                should_probe=True,
                reason="Cache entered critical cooling window; automated probe approved",
                session_id=session_id,
                probe_token_budget=cfg.probe_max_tokens,
                suggested_probe_prompt="ping",
                target_ttl_renewal_seconds=spec.extended_ttl_seconds,
            )

    def record_probe_execution(
        self,
        session_id: str,
        probe_tokens: int,
        renewed_ttl_seconds: int,
        estimated_probe_cost_usd: float,
        now: datetime | None = None,
    ) -> HeartbeatExecutionRecord:
        """Audit and increment consecutive probe count upon probe dispatch."""
        ts = now or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        with self._lock:
            current_index = self._consecutive_heartbeats.get(session_id, 0) + 1
            self._consecutive_heartbeats[session_id] = current_index

            record = HeartbeatExecutionRecord(
                session_id=session_id,
                executed_at_iso=ts.isoformat(),
                probe_tokens=probe_tokens,
                renewed_ttl_seconds=renewed_ttl_seconds,
                estimated_probe_cost_usd=estimated_probe_cost_usd,
                consecutive_heartbeat_index=current_index,
            )

            if session_id not in self._history:
                self._history[session_id] = []
            self._history[session_id].append(record)
            return record

    def on_user_activity(self, session_id: str) -> None:
        """Reset consecutive probe counter when human user interacts."""
        with self._lock:
            self._consecutive_heartbeats[session_id] = 0

    def get_consecutive_count(self, session_id: str) -> int:
        """Get consecutive heartbeat count for a session."""
        with self._lock:
            return self._consecutive_heartbeats.get(session_id, 0)

    def get_probe_history(self, session_id: str) -> list[HeartbeatExecutionRecord]:
        """Return history of executed probes for a session."""
        with self._lock:
            return list(self._history.get(session_id, []))

    def reset_session(self, session_id: str) -> None:
        """Clean up scheduler tracking for session."""
        with self._lock:
            self._consecutive_heartbeats.pop(session_id, None)
            self._history.pop(session_id, None)
