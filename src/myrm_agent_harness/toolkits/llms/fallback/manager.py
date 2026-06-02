"""Model fallback manager with cooldown and candidate pool.

Manages multiple fallback models with cooldown periods to avoid repeatedly
trying failed models.

[INPUT]
- llms.errors.classifier (POS: error classification)
- infra.tracing (POS: distributed tracing)

[OUTPUT]
- ModelCandidate: model candidate dataclass
- ModelFallbackManager: fallback manager

[POS]
Model fallback manager. Maintains candidate pool, cooldown state, and selects the next available model.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from myrm_agent_harness.infra.tracing import get_meter, get_tracer
from myrm_agent_harness.toolkits.llms.errors import FailoverReason, classify_failover_reason, get_probe_policy
from myrm_agent_harness.toolkits.llms.errors.classifier import classify_error

from .config import ProbeConfig
from .context import get_active_failover_emitter
from .events import FailoverCallback, FailoverEvent, RecoveryCallback, RecoveryEvent
from .health_check import lightweight_health_check
from .probe_throttle import get_global_probe_throttle
from .scenario import ModelMetrics, ScenarioType, select_by_scenario

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)
meter = get_meter(__name__)

T = TypeVar("T")

# Default fallback values (used when error reason is unknown)
DEFAULT_COOLDOWN_MS = 60_000  # 60 seconds
DEFAULT_PROBE_INTERVAL_MS = 30_000  # 30 seconds
DEFAULT_MAX_PROBE_ATTEMPTS = 3


@dataclass
class ModelCandidate[T]:
    """Model candidate with priority, exponential backoff, and error-driven probe policy.

    Attributes:
        name: Model name (for logging)
        priority: Priority (lower = higher priority)
        call_fn: Async callable that executes the model
        llm_instance: Optional LLM instance for lightweight health checks
        cost: Relative cost (0.0-1.0, lower is better, default: 0.5)
        latency: Relative latency (0.0-1.0, lower is better, default: 0.5)
        quality: Relative quality (0.0-1.0, higher is better, default: 0.5)
        cooldown_until: Timestamp (ms) until which this model is in cooldown
        cooldown_started_at: Timestamp (ms) when cooldown started (for accurate downtime calculation)
        probe_count: Number of probe attempts during current cooldown
        last_probe_at: Timestamp (ms) of last probe attempt
        last_error_reason: Last error reason (for error-driven probe policy)
        consecutive_failures: Number of consecutive failures (drives exponential backoff)
    """

    name: str
    priority: int
    call_fn: Callable[[], Awaitable[T]]
    llm_instance: Any | None = field(default=None)
    cost: float = field(default=0.5)
    latency: float = field(default=0.5)
    quality: float = field(default=0.5)
    cooldown_until: float = field(default=0.0)
    cooldown_started_at: float = field(default=0.0)
    probe_count: int = field(default=0)
    last_probe_at: float = field(default=0.0)
    last_error_reason: FailoverReason | None = field(default=None)
    consecutive_failures: int = field(default=0)
    _cached_metrics: ModelMetrics | None = field(default=None, init=False, repr=False)

    def is_in_cooldown(self, now_ms: float) -> bool:
        """Check if model is in cooldown period."""
        return now_ms < self.cooldown_until

    def get_metrics(self) -> ModelMetrics:
        """Get cached ModelMetrics or create new one.

        Returns:
            Cached or newly created ModelMetrics
        """
        if self._cached_metrics is None:
            self._cached_metrics = ModelMetrics(
                name=self.name,
                priority=self.priority,
                cost=self.cost,
                latency=self.latency,
                quality=self.quality,
            )
        return self._cached_metrics

    def should_probe(self, now_ms: float) -> bool:
        """Check if model should be probed during cooldown (error-driven strategy).

        Uses error-specific probe policy to determine probe timing and limits.

        Returns:
            True if probe is allowed
        """
        if not self.is_in_cooldown(now_ms):
            return True

        # Get error-driven probe policy
        if self.last_error_reason:
            policy = get_probe_policy(self.last_error_reason)
        else:
            # Fallback to default policy
            policy = get_probe_policy(FailoverReason.UNKNOWN)

        # Check if probing is enabled for this error type
        if not policy.enabled:
            return False

        # Check if max probe attempts reached
        if self.probe_count >= policy.max_attempts:
            return False

        time_since_cooldown_start = now_ms - self.cooldown_started_at

        # First probe after interval from cooldown start
        if self.probe_count == 0:
            return time_since_cooldown_start >= policy.interval_ms

        # Subsequent probes: interval since last probe
        if self.last_probe_at > 0:
            return now_ms - self.last_probe_at >= policy.interval_ms

        return False

    def enter_cooldown(
        self,
        now_ms: float,
        error_reason: FailoverReason,
        consecutive_failures: int = 0,
    ) -> None:
        """Enter cooldown period with error-driven policy and exponential backoff.

        Uses exponential backoff: base_cooldown * (2 ^ consecutive_failures)
        Capped at 10 minutes to prevent excessive delays.

        Args:
            now_ms: Current timestamp in milliseconds
            error_reason: Error reason that triggered cooldown
            consecutive_failures: Number of consecutive failures (for exponential backoff)
        """
        self.last_error_reason = error_reason
        policy = get_probe_policy(error_reason)

        # Apply exponential backoff based on consecutive failures
        backoff_multiplier = 2 ** min(consecutive_failures, 5)  # Cap at 2^5 = 32x
        cooldown_ms = policy.cooldown_ms * backoff_multiplier
        max_cooldown_ms = 10 * 60 * 1000  # 10 minutes max
        cooldown_ms = min(cooldown_ms, max_cooldown_ms)

        self.cooldown_started_at = now_ms
        self.cooldown_until = now_ms + cooldown_ms
        self.probe_count = 0
        self.last_probe_at = 0.0

    def record_probe(self, now_ms: float, success: bool) -> None:
        """Record a probe attempt.

        Args:
            now_ms: Current timestamp in milliseconds
            success: Whether probe succeeded
        """
        self.last_probe_at = now_ms
        self.probe_count += 1

        if success:
            # Probe succeeded - exit cooldown and reset consecutive failures
            self.cooldown_until = 0.0
            self.probe_count = 0
            self.consecutive_failures = 0


class ModelFallbackManager[T]:
    """Model fallback manager with cooldown and candidate pool.

    Features:
    - Multiple fallback candidates
    - Cooldown period for failed models
    - Priority-based selection
    - Decision logging

    Example:
        manager = ModelFallbackManager()
        manager.add_candidate("gpt-4", 0, lambda: primary_llm.ainvoke(messages))
        manager.add_candidate("claude-3", 1, lambda: fallback_llm.ainvoke(messages))

        result = await manager.execute()
    """

    def __init__(
        self,
        probe_config: ProbeConfig | None = None,
        on_failover: FailoverCallback | None = None,
        on_recovery: RecoveryCallback | None = None,
    ) -> None:
        """Initialize fallback manager.

        Args:
            probe_config: Optional probe and cooldown configuration (uses defaults if None)
            on_failover: Optional callback function called when failover occurs
            on_recovery: Optional callback function called when model recovers
        """
        self._candidates: list[ModelCandidate[T]] = []
        self._probe_config = probe_config or ProbeConfig()
        self._global_throttle = get_global_probe_throttle()
        self._on_failover = on_failover
        self._on_recovery = on_recovery

        # Metrics
        self._attempt_counter = meter.create_counter(
            name="model_fallback_attempt_total",
            description="Total number of model attempts",
            unit="1",
        )
        self._success_counter = meter.create_counter(
            name="model_fallback_success_total",
            description="Total number of successful model calls",
            unit="1",
        )
        self._failure_counter = meter.create_counter(
            name="model_fallback_failure_total",
            description="Total number of failed model calls",
            unit="1",
        )
        self._cooldown_counter = meter.create_counter(
            name="model_fallback_cooldown_total",
            description="Total number of models entering cooldown",
            unit="1",
        )
        self._probe_counter = meter.create_counter(
            name="model_fallback_probe_total",
            description="Total number of probe attempts",
            unit="1",
        )
        self._execution_duration = meter.create_histogram(
            name="model_fallback_duration_ms",
            description="Model execution duration in milliseconds",
            unit="ms",
        )
        self._failover_total = meter.create_counter(
            name="model_fallback_failover_total",
            description="Total number of failovers (model switches)",
            unit="1",
        )
        self._recovery_total = meter.create_counter(
            name="model_fallback_recovery_total",
            description="Total number of successful recoveries",
            unit="1",
        )
        self._recovery_duration = meter.create_histogram(
            name="model_fallback_recovery_duration_ms",
            description="Model recovery duration (downtime) in milliseconds",
            unit="ms",
        )
        self._probe_success_rate = meter.create_histogram(
            name="model_fallback_probe_success_rate",
            description="Probe success rate (0.0-1.0)",
            unit="1",
        )

    def add_candidate(
        self,
        name: str,
        priority: int,
        call_fn: Callable[[], Awaitable[T]],
        llm_instance: Any | None = None,
        cost: float = 0.5,
        latency: float = 0.5,
        quality: float = 0.5,
    ) -> None:
        """Add a model candidate.

        Args:
            name: Model name
            priority: Priority (lower = higher priority)
            call_fn: Async callable
            llm_instance: Optional LLM instance for lightweight health checks
            cost: Relative cost (0.0-1.0, lower is better, default: 0.5)
            latency: Relative latency (0.0-1.0, lower is better, default: 0.5)
            quality: Relative quality (0.0-1.0, higher is better, default: 0.5)
        """
        candidate = ModelCandidate(
            name=name,
            priority=priority,
            call_fn=call_fn,
            llm_instance=llm_instance,
            cost=cost,
            latency=latency,
            quality=quality,
        )
        self._candidates.append(candidate)

        # Sort by priority
        self._candidates.sort(key=lambda c: c.priority)

        logger.debug(
            f"Added model candidate: {name} (priority={priority}, cost={cost}, latency={latency}, quality={quality})"
        )

    def _get_available_candidates(
        self,
        now_ms: float,
        scenario: ScenarioType = ScenarioType.BALANCED,
    ) -> list[ModelCandidate[T]]:
        """Get candidates not in cooldown or eligible for probing.

        Uses scenario-aware selection to order candidates optimally.

        Args:
            now_ms: Current timestamp in milliseconds
            scenario: Usage scenario for model selection

        Returns:
            List of available candidates, ordered by scenario-specific criteria
        """
        # Filter available candidates
        available = [c for c in self._candidates if not c.is_in_cooldown(now_ms) or c.should_probe(now_ms)]

        if not available:
            return []

        # If only one candidate, no need for scenario selection
        if len(available) == 1:
            return available

        # Use cached ModelMetrics for scenario-aware selection
        metrics_list = [c.get_metrics() for c in available]

        # Select best candidate for scenario
        best_metrics = select_by_scenario(metrics_list, scenario)

        # Reorder candidates: best first, then rest by priority
        best_candidate = next(c for c in available if c.name == best_metrics.name)
        other_candidates = [c for c in available if c.name != best_metrics.name]

        return [best_candidate, *other_candidates]

    async def execute(
        self,
        scenario: ScenarioType = ScenarioType.BALANCED,
        now_ms: float | None = None,
    ) -> T:
        """Execute with automatic fallback and scenario-aware selection.

        Tries candidates using scenario-specific ordering (e.g., latency-first
        for REALTIME, cost-first for BATCH). If a candidate fails with a
        failoverable error, it enters cooldown and the next candidate is tried.

        Args:
            scenario: Usage scenario for model selection (default: BALANCED)
            now_ms: Current timestamp in milliseconds (for testing, default: current time)

        Returns:
            Result from successful candidate

        Raises:
            Exception: If all candidates fail or are in cooldown
        """
        if not self._candidates:
            raise ValueError("No model candidates configured")

        if now_ms is None:
            now_ms = time.time() * 1000
        available = self._get_available_candidates(now_ms, scenario)

        if not available:
            # All models in cooldown - try primary anyway
            logger.warning("All models in cooldown, attempting primary model anyway")
            available = [self._candidates[0]]

        with tracer.start_as_current_span("model_fallback") as span:
            span.set_attribute("fallback.total_candidates", len(self._candidates))
            span.set_attribute("fallback.available_candidates", len(available))
            span.set_attribute("fallback.scenario", scenario.value)

            last_error: Exception | None = None

            for idx, candidate in enumerate(available):
                is_probe = candidate.is_in_cooldown(now_ms)

                # Check global probe throttle
                if is_probe and not self._global_throttle.should_probe(candidate.name, now_ms):
                    logger.debug(
                        f"Skipping probe for {candidate.name}: globally throttled (probed recently by another request)"
                    )
                    continue

                start_time = time.time()

                try:
                    if is_probe:
                        logger.debug(f"Probing model during cooldown: {candidate.name}")
                        self._probe_counter.add(1, {"model": candidate.name})

                        # Lightweight health check for probes (if LLM instance available)
                        if candidate.llm_instance:
                            logger.debug(f"Running lightweight health check: {candidate.name}")
                            health_ok = await lightweight_health_check(candidate.llm_instance)
                            if not health_ok:
                                logger.debug(f"Health check failed: {candidate.name}")
                                # Skip this candidate, continue to next
                                continue
                            logger.debug(f"Health check passed: {candidate.name}")
                    else:
                        logger.debug(f"Attempting model: {candidate.name}")

                    self._attempt_counter.add(1, {"model": candidate.name, "is_probe": str(is_probe)})

                    span.add_event(
                        "attempt_model",
                        attributes={
                            "model": candidate.name,
                            "priority": candidate.priority,
                            "attempt": idx + 1,
                            "is_probe": is_probe,
                        },
                    )

                    result = await candidate.call_fn()

                    # Success
                    duration_ms = (time.time() - start_time) * 1000
                    span.set_attribute("fallback.success_model", candidate.name)
                    span.set_attribute("fallback.attempts", idx + 1)

                    self._success_counter.add(1, {"model": candidate.name})
                    self._execution_duration.record(duration_ms, {"model": candidate.name, "status": "success"})

                    # Reset consecutive failures on success
                    candidate.consecutive_failures = 0

                    if is_probe:
                        # Calculate downtime and save probe count before recording success
                        downtime_ms = int(now_ms - candidate.cooldown_started_at)
                        probe_attempts = candidate.probe_count + 1  # +1 for current probe

                        candidate.record_probe(now_ms, success=True)
                        logger.info(f"Probe successful: {candidate.name} recovered during cooldown")

                        # Trigger recovery callback + ctx-bound emitter
                        recovery_emitter = get_active_failover_emitter()
                        if self._on_recovery is not None or recovery_emitter is not None:
                            recovery_event = RecoveryEvent(
                                model=candidate.name,
                                downtime_ms=downtime_ms,
                                probe_count=probe_attempts,
                                was_in_cooldown=True,
                            )

                            # Record recovery metrics
                            self._recovery_total.add(1, {"model": candidate.name})
                            self._recovery_duration.record(downtime_ms, {"model": candidate.name})
                            if probe_attempts > 0:
                                probe_success_rate = 1.0 / probe_attempts
                                self._probe_success_rate.record(probe_success_rate, {"model": candidate.name})

                            if self._on_recovery is not None:
                                try:
                                    await self._on_recovery(recovery_event)
                                except Exception as callback_exc:
                                    logger.warning(
                                        f"Recovery callback failed: {callback_exc}",
                                        exc_info=True,
                                    )

                            if recovery_emitter is not None:
                                try:
                                    await recovery_emitter.emit_recovery(recovery_event)
                                except Exception as emit_exc:
                                    logger.warning(
                                        f"Recovery emitter failed: {emit_exc}",
                                        exc_info=True,
                                    )

                    if last_error is not None:
                        logger.info(f"Fallback successful: {candidate.name} succeeded after previous failures")

                    return result

                except Exception as exc:
                    duration_ms = (time.time() - start_time) * 1000
                    # Use new three-layer error classification
                    error_reason = classify_failover_reason(exc)
                    error_kind = classify_error(exc)  # Keep for backward compatibility

                    span.add_event(
                        "model_failed",
                        attributes={
                            "model": candidate.name,
                            "error_reason": error_reason.value,
                            "error_kind": error_kind.value,
                            "recoverability": error_reason.recoverability.value,
                            "is_failoverable": error_reason.is_failoverable,
                            "is_probe": is_probe,
                        },
                    )

                    self._failure_counter.add(1, {"model": candidate.name, "error_kind": error_reason.value})
                    self._execution_duration.record(duration_ms, {"model": candidate.name, "status": "failed"})

                    if not error_reason.is_failoverable:
                        # Non-failoverable error - propagate immediately
                        logger.warning(
                            f"Model {candidate.name} failed with non-failoverable error: "
                            f"{error_reason.value} (recoverability: {error_reason.recoverability.value})"
                        )
                        span.set_attribute("fallback.non_failoverable", True)
                        span.record_exception(exc)
                        raise

                    # Failoverable error
                    if is_probe:
                        # Probe failed - record and continue
                        candidate.record_probe(now_ms, success=False)
                        policy = get_probe_policy(error_reason)
                        logger.debug(
                            f"Probe failed for {candidate.name} (attempt {candidate.probe_count}/{policy.max_attempts})"
                        )
                    else:
                        # Normal failure - enter cooldown with exponential backoff
                        candidate.consecutive_failures += 1
                        candidate.enter_cooldown(now_ms, error_reason, candidate.consecutive_failures)
                        policy = get_probe_policy(error_reason)
                        backoff_multiplier = 2 ** min(candidate.consecutive_failures, 5)
                        actual_cooldown_ms = min(policy.cooldown_ms * backoff_multiplier, 10 * 60 * 1000)
                        self._cooldown_counter.add(1, {"model": candidate.name, "error_reason": error_reason.value})
                        logger.warning(
                            f"Model {candidate.name} failed with {error_reason.value} "
                            f"(consecutive={candidate.consecutive_failures}), "
                            f"entering cooldown for {actual_cooldown_ms / 1000:.0f}s"
                        )

                    last_error = exc

                    # If this was the last candidate, propagate error
                    if candidate == available[-1]:
                        logger.error(f"All available models failed, last error: {error_reason.value}")
                        span.set_attribute("fallback.all_failed", True)
                        span.record_exception(exc)
                        raise

                    # Failover to next candidate - trigger callback + ctx-bound emitter
                    emitter = get_active_failover_emitter()
                    if idx < len(available) - 1 and (
                        self._on_failover is not None or emitter is not None
                    ):
                        next_candidate = available[idx + 1]
                        policy = get_probe_policy(error_reason)
                        event = FailoverEvent(
                            from_model=candidate.name,
                            to_model=next_candidate.name,
                            reason=error_reason,
                            error_message=str(exc),
                            cooldown_ms=policy.cooldown_ms,
                            attempt_count=candidate.consecutive_failures + 1,
                            available_candidates=[c.name for c in available],
                            scenario=scenario.value,
                        )

                        # Record failover metrics
                        self._failover_total.add(
                            1,
                            {
                                "from_model": candidate.name,
                                "to_model": next_candidate.name,
                                "reason": error_reason.value,
                            },
                        )

                        if self._on_failover is not None:
                            try:
                                await self._on_failover(event)
                            except Exception as callback_exc:
                                logger.warning(
                                    f"Failover callback failed: {callback_exc}",
                                    exc_info=True,
                                )

                        # Surface the event through the context-bound emitter so
                        # streaming surfaces (SSE, telemetry, log sinks) can
                        # publish without coupling the manager to any one wire.
                        if emitter is not None:
                            try:
                                await emitter.emit_failover(event)
                            except Exception as emit_exc:
                                logger.warning(
                                    f"Failover emitter failed: {emit_exc}",
                                    exc_info=True,
                                )

            # Should not reach here
            if last_error:
                raise last_error

            raise RuntimeError("No models available")

    def reset_cooldowns(self) -> None:
        """Reset all cooldown periods (for testing)."""
        for candidate in self._candidates:
            candidate.cooldown_until = 0.0
