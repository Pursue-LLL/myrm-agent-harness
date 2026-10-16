"""Priority-ordered search provider chain runner with self-healing quota tracking.

[INPUT]
- myrm_agent_harness.toolkits.web_search.providers.web_searcher::WebSearcher (POS: Web search orchestrator)
- myrm_agent_harness.toolkits.web_search.core.error_handling::is_quota_or_rate_limit_error, is_persistent_quota_depleted_error

[OUTPUT]
- ProviderQuotaStatus: Enum of provider health states
- ProviderQuotaState: Dataclass tracking individual provider status and cooldowns
- ProviderQuotaTracker: Thread-safe in-memory tracker whose depleted and rate-limited states both expire after a cooldown
- default_quota_tracker: Default singleton instance of ProviderQuotaTracker
- search_provider_chain: async failover search across priority-ordered provider configs with smart skip

[POS]
Executes N-provider priority chain with wall-clock budget, per-hop allowance for hung providers, self-healing quota
auto-skip, and chain_hop telemetry.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.web_search.core.error_handling import (
    is_persistent_quota_depleted_error,
    is_quota_or_rate_limit_error,
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
# Quota resets (billing cycles, top-ups) happen out of band and the tracker cannot observe them, so a depleted
# provider is probed again after this window; a provider that is still exhausted is re-marked by that probe.
_DEFAULT_DEPLETED_COOLDOWN_SECONDS = 3600.0


class ProviderQuotaStatus(StrEnum):
    """Health and quota state for an upstream search provider."""

    HEALTHY = "healthy"
    RATE_LIMITED = "rate_limited"
    DEPLETED = "depleted"


@dataclass
class ProviderQuotaState:
    """State snapshot for a specific provider."""

    status: ProviderQuotaStatus = ProviderQuotaStatus.HEALTHY
    unavailable_until: float = 0.0  # time.monotonic() deadline after which the provider is probed again
    reason: str = ""


class ProviderQuotaTracker:
    """Thread-safe state machine tracking search provider quota depletion and transient throttling."""

    def __init__(self) -> None:
        self._states: dict[str, ProviderQuotaState] = {}
        self._lock = threading.Lock()

    def get_status(self, provider: str) -> tuple[ProviderQuotaStatus, str]:
        """Check provider status; an elapsed cooldown drops the state so the provider is probed again."""
        with self._lock:
            state = self._states.get(provider)
            if state is None:
                return ProviderQuotaStatus.HEALTHY, ""
            if time.monotonic() < state.unavailable_until:
                return state.status, state.reason
            del self._states[provider]
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
                unavailable_until=time.monotonic() + cooldown_seconds,
                reason=reason,
            )

    def mark_depleted(
        self,
        provider: str,
        reason: str = "",
        cooldown_seconds: float = _DEFAULT_DEPLETED_COOLDOWN_SECONDS,
    ) -> None:
        """Mark provider as quota-exhausted until the cooldown elapses."""
        with self._lock:
            self._states[provider] = ProviderQuotaState(
                status=ProviderQuotaStatus.DEPLETED,
                unavailable_until=time.monotonic() + cooldown_seconds,
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


default_quota_tracker = ProviderQuotaTracker()


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

    Any failed hop (quota, rate limit, outage, bad credentials, no answer in time) advances to the next provider until
    the chain's wall-clock budget is spent; only quota and rate-limit failures also put the provider on a cooldown.
    A hop that has not answered after half of the remaining budget is abandoned unless it is the last one.

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

    final_index = len(execution_chain) - 1
    for index, hop_config in enumerate(execution_chain):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        provider = hop_config.search_service
        if index > 0:
            # A hop is counted when the next provider is attempted, not when the previous one fails: if that failure
            # spent the chain budget, the deadline check above ends the chain and no hop happened.
            previous_provider = execution_chain[index - 1].search_service
            logger.warning("Search chain hop '%s' failed, trying next provider: %s", previous_provider, provider)
            if metrics is not None:
                metrics.record_chain_hop(from_provider=previous_provider, to_provider=provider)
        hop_searcher = WebSearcher(hop_config, metrics=metrics)
        # A hung hop would otherwise outlast the whole budget (its coalescing wait and retries add up to more than
        # the chain allows) and no later provider would ever run, so every hop but the last yields after half of what
        # remains. The last hop has nobody to hand over to; capping it would only add a doomed extra request.
        allowance = remaining / 2 if index < final_index else None
        try:
            async with asyncio.timeout(allowance):
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
            elif is_quota_or_rate_limit_error(exc):
                logger.warning(
                    "Search provider '%s' transient rate limit hit, cooling down: %s",
                    provider,
                    exc,
                )
                tracker.mark_rate_limited(provider, reason=str(exc))

    if last_error is None:
        message = "All search providers in chain failed"
    else:
        # A timeout carries no text; the exception type keeps the failure reason readable downstream.
        message = str(last_error) or type(last_error).__name__
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
