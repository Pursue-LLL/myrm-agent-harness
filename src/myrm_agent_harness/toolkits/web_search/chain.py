"""Priority-ordered search provider chain runner.

[INPUT]
- myrm_agent_harness.toolkits.web_search.web_searcher::WebSearcher (POS: Web search orchestrator)
- myrm_agent_harness.toolkits.web_search.error_handling::is_quota_or_rate_limit_error, is_retryable_search_error

[OUTPUT]
- search_provider_chain: async failover search across priority-ordered provider configs

[POS]
Executes N-provider priority chain (1→2→…→5) with wall-clock budget and chain_hop metrics.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.web_search.error_handling import (
    is_quota_or_rate_limit_error,
    is_retryable_search_error,
)
from myrm_agent_harness.toolkits.web_search.exceptions import (
    AllQueriesFailedError,
    SearchAPIError,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.web_search.common import SearchResult
    from myrm_agent_harness.toolkits.web_search.metrics import WebSearchMetrics
    from myrm_agent_harness.toolkits.web_search.web_searcher import (
        SearchServiceConfig,
    )

logger = logging.getLogger(__name__)

_CHAIN_WALL_CLOCK_SECONDS = 45.0


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
) -> tuple[list[SearchResult], str]:
    """Search using a priority-ordered provider chain.

    Returns:
        Tuple of (results, winning provider slug).
    """
    from myrm_agent_harness.toolkits.web_search.web_searcher import WebSearcher

    if not chain:
        raise SearchAPIError("Search provider chain is empty")

    last_error: Exception | None = None
    deadline = time.monotonic() + _CHAIN_WALL_CLOCK_SECONDS

    for index, hop_config in enumerate(chain):
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
                    from_provider=chain[index - 1].search_service, to_provider=provider
                )
                if metrics is not None:
                    metrics.record_chain_hop(
                        from_provider=chain[index - 1].search_service,
                        to_provider=provider,
                    )
            return results, provider
        except Exception as exc:
            last_error = exc
            if _should_stop_chain(exc):
                logger.warning(
                    "Search chain hop '%s' failed with retryable error, not advancing chain: %s",
                    provider,
                    exc,
                )
                break
            if index < len(chain) - 1:
                logger.warning(
                    "Search chain hop '%s' failed, trying next provider: %s",
                    provider,
                    chain[index + 1].search_service,
                )
                if metrics is not None:
                    metrics.record_chain_hop(
                        from_provider=provider,
                        to_provider=chain[index + 1].search_service,
                    )
                continue
            break

    message = (
        str(last_error)
        if last_error is not None
        else "All search providers in chain failed"
    )
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
