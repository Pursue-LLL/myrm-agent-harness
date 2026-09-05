"""Priority-ordered search provider chain runner with self-healing quota tracking.

[INPUT]
- myrm_agent_harness.toolkits.web_search.providers.web_searcher::WebSearcher (POS: Web search orchestrator)
- myrm_agent_harness.toolkits.web_search.core.error_handling::is_quota_or_rate_limit_error, is_persistent_quota_depleted_error, is_retryable_search_error

[OUTPUT]
- ProviderQuotaStatus: Enum of provider health states
- ProviderQuotaState: Dataclass tracking individual provider status and cooldowns
- ProviderQuotaTracker: Thread-safe in-memory tracker for provider quota and rate-limit states
- default_quota_tracker: Default singleton instance of ProviderQuotaTracker
- search_provider_chain: async failover search across priority-ordered provider configs with smart skip

[POS]
Executes N-provider priority chain with wall-clock budget, self-healing quota auto-skip, and chain_hop telemetry.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.web_search.core.error_handling import (
    is_persistent_quota_depleted_error,
    is_quota_or_rate_limit_error,
    is_retryable_search_error,
)
from myrm_agent_harness.toolkits.web_search.core.exceptions import (
    AllQueriesFailedError,
    SearchAPIError,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.web_search.core.common import SearchResult
    from myrm_agent_harness.toolkits.web_search.core.metrics import WebSearchMetrics
    from myrm_agent_harness.toolkits.web_search.providers.web_searcher import (
        SearchServiceConfig,
    )

logger = logging.getLogger(__name__)

_CHAIN_WALL_CLOCK_SECONDS = 45.0
_DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 5.0


class ProviderQuotaStatus(str, Enum):
    """Health and quota state for an upstream search provider."""

    HEALTHY = "healthy"
    RATE_LIMITED = "rate_limited"
    DEPLETED = "depleted"


@dataclass
class ProviderQuotaState:
    """State snapshot for a specific provider."""

    status: ProviderQuotaStatus = ProviderQuotaStatus.HEALTHY
    rate_limited_until: float = 0.0
    depleted_at: float = 0.0
    reason: str = ""


class ProviderQuotaTracker:
    """Thread-safe state machine tracking search provider quota depletion and transient throttling."""

    def __init__(self) -> None:
        self._states: dict[str, ProviderQuotaState] = {}
        self._lock = threading.Lock()

    def get_status(self, provider: str) -> tuple[ProviderQuotaStatus, str]:
        """Check provider status, handling transient rate-limit expiration automatically."""
        with self._lock:
            state = self._states.get(provider)
            if state is None:
                return ProviderQuotaStatus.HEALTHY, ""
            if state.status == ProviderQuotaStatus.DEPLETED:
                return ProviderQuotaStatus.DEPLETED, state.reason
            if state.status == ProviderQuotaStatus.RATE_LIMITED:
                if time.monotonic() < state.rate_limited_until:
                    return ProviderQuotaStatus.RATE_LIMITED, state.reason
                state.status = ProviderQuotaStatus.HEALTHY
                return ProviderQuotaStatus.HEALTHY, ""
            return ProviderQuotaStatus.HEALTHY, ""

    def mark_rate_limited(
        self,
        provider: str,
        cooldown_seconds: float = _DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS,
        reason: str = "",
    ) -> None:
        """Mark provider as transiently throttled with auto-recovery cooldown."""
        with self._lock:
            self._states[provider] = ProviderQuotaState(
                status=ProviderQuotaStatus.RATE_LIMITED,
                rate_limited_until=time.monotonic() + cooldown_seconds,
                reason=reason,
            )

    def mark_depleted(self, provider: str, reason: str = "") -> None:
        """Mark provider as persistently depleted until explicit reset."""
        with self._lock:
            self._states[provider] = ProviderQuotaState(
                status=ProviderQuotaStatus.DEPLETED,
                depleted_at=time.time(),
                reason=reason,
            )

    def reset_provider(self, provider: str) -> None:
        """Clear quota state for a specific provider."""
        with self._lock:
            self._states.pop(provider, None)

    def reset_all(self) -> None:
        """Reset all tracked provider quota states."""
        with self._lock:
            self._states.clear()

    def get_all_states(self) -> dict[str, dict[str, object]]:
        """Return snapshot of all provider states for observability."""
        with self._lock:
            now = time.monotonic()
            result: dict[str, dict[str, object]] = {}
            for provider, state in self._states.items():
                is_active_rl = (
                    state.status == ProviderQuotaStatus.RATE_LIMITED
                    and now < state.rate_limited_until
                )
                effective_status = (
                    state.status
                    if state.status != ProviderQuotaStatus.RATE_LIMITED or is_active_rl
                    else ProviderQuotaStatus.HEALTHY
                )
                result[provider] = {
                    "status": effective_status.value,
                    "reason": state.reason,
                    "depleted_at": state.depleted_at,
                    "cooldown_remaining": (
                        max(0.0, state.rate_limited_until - now) if is_active_rl else 0.0
                    ),
                }
            return result


default_quota_tracker = ProviderQuotaTracker()


def _should_stop_chain(exc: BaseException) -> bool:
    """Return True when chain must not advance to the next provider."""
    if is_quota_or_rate_limit_error(exc):
        return False
    if isinstance(exc, SearchAPIError) and exc.context is not None:
        return exc.context.retryable
    return is_retryable_search_error(exc)


async def search_provider_chain(
    chain: list[SearchServiceConfig],
    query: str,
    num_results: int,
    *,
    metrics: WebSearchMetrics | None = None,
    extra_params_override: dict[str, str | int | bool] | None = None,
    quota_tracker: ProviderQuotaTracker | None = None,
) -> tuple[list[SearchResult], str]:
    """Search using a priority-ordered provider chain with intelligent quota auto-skip.

    Returns:
        Tuple of (results, winning provider slug).
    """
    from myrm_agent_harness.toolkits.web_search.providers.web_searcher import WebSearcher

    if not chain:
        raise SearchAPIError("Search provider chain is empty")

    tracker = quota_tracker if quota_tracker is not None else default_quota_tracker
    last_error: Exception | None = None
    deadline = time.monotonic() + _CHAIN_WALL_CLOCK_SECONDS

    # Filter or reorder based on tracker status to avoid calling known-depleted providers
    active_chain: list[SearchServiceConfig] = []
    skipped_providers: list[tuple[str, str]] = []

    for config in chain:
        status, reason = tracker.get_status(config.search_service)
        if status in (ProviderQuotaStatus.DEPLETED, ProviderQuotaStatus.RATE_LIMITED):
            skipped_providers.append((config.search_service, f"{status.value}: {reason}"))
        else:
            active_chain.append(config)

    # Fallback: if all providers are marked depleted/throttled, attempt original chain anyway
    execution_chain = active_chain if active_chain else chain
    if not active_chain and skipped_providers:
        logger.warning(
            "All providers in search chain were marked unavailable (%s); forcing retry on full chain",
            skipped_providers,
        )

    for index, hop_config in enumerate(execution_chain):
        if time.monotonic() >= deadline:
            break
        provider = hop_config.search_service
        hop_searcher = WebSearcher(hop_config, metrics=metrics)
        try:
            results = await hop_searcher.search(
                query=query,
                num_results=num_results,
                extra_params_override=extra_params_override,
            )
            if index > 0:
                await _dispatch_chain_hop_event(
                    from_provider=execution_chain[index - 1].search_service,
                    to_provider=provider,
                )
                if metrics is not None:
                    metrics.record_chain_hop(
                        from_provider=execution_chain[index - 1].search_service,
                        to_provider=provider,
                    )
            return results, provider
        except Exception as exc:
            last_error = exc

            # Update tracker state based on error severity
            if is_persistent_quota_depleted_error(exc):
                logger.warning(
                    "Search provider '%s' persistent quota depleted, marking depleted: %s",
                    provider,
                    exc,
                )
                tracker.mark_depleted(provider, reason=str(exc))
                if metrics is not None:
                    metrics.record_provider_search(provider, success=False, quota_exceeded=True)
            elif is_quota_or_rate_limit_error(exc):
                logger.warning(
                    "Search provider '%s' transient rate limit hit, cooling down: %s",
                    provider,
                    exc,
                )
                tracker.mark_rate_limited(provider, cooldown_seconds=5.0, reason=str(exc))
                if metrics is not None:
                    metrics.record_provider_search(provider, success=False, quota_exceeded=False)

            if _should_stop_chain(exc):
                logger.warning(
                    "Search chain hop '%s' failed with retryable error, not advancing chain: %s",
                    provider,
                    exc,
                )
                break
            if index < len(execution_chain) - 1:
                next_provider = execution_chain[index + 1].search_service
                logger.warning(
                    "Search chain hop '%s' failed, trying next provider: %s",
                    provider,
                    next_provider,
                )
                if metrics is not None:
                    metrics.record_chain_hop(
                        from_provider=provider,
                        to_provider=next_provider,
                    )
                continue
            break

    message = str(last_error) if last_error is not None else "All search providers in chain failed"
    raise AllQueriesFailedError(message) from last_error


async def _dispatch_chain_hop_event(*, from_provider: str, to_provider: str) -> None:
    try:
        from myrm_agent_harness.utils.event_utils import dispatch_custom_event

        await dispatch_custom_event(
            "agent_status",
            {
                "event": "tool_fallback",
                "tool": "web_search_tool",
                "fallback_type": "chain_failover",
                "message": f"Search provider switched ({from_provider} → {to_provider})",
                "from_provider": from_provider,
                "to_provider": to_provider,
            },
        )
    except Exception:
        pass
