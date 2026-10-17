"""Search service factory — builds the concrete search client for one provider config.

[INPUT]
web_search.core.common::SearchResult (POS: Unified search result dataclass)
web_search.core.exceptions::SearchConfigError (POS: Search exception types)
web_search.providers.litellm_search::LiteLLMSearch (POS: LiteLLM unified search client, imported on first build so litellm stays out of package import)
web_search.providers.volcengine_doubao_search::VolcengineDoubaoSearch (POS: Volcengine native search client)

[OUTPUT]
SearchService: Structural type every concrete search client satisfies
build_search_service: Turns a SearchServiceConfig into a ready client, rejecting missing credentials up front

[POS]
Provider wiring for WebSearcher: decides native vs LiteLLM client, direct vs gateway routing, and which
credentials are mandatory. Holds no state; caching and retry stay in WebSearcher.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from myrm_agent_harness.toolkits.web_search.core.common import SearchResult
from myrm_agent_harness.toolkits.web_search.core.exceptions import SearchConfigError

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.web_search.providers.web_searcher import SearchServiceConfig

logger = logging.getLogger(__name__)


class SearchService(Protocol):
    """Async search client for one provider."""

    async def search(self, query: str, num_results: int = 5, **kwargs: object) -> list[SearchResult]: ...


def require_api_key(config: SearchServiceConfig) -> str:
    if not config.api_key:
        raise SearchConfigError(
            f"{config.search_service} search requires API key configuration",
            config_key="api_key",
        )
    return config.api_key


def describe_credential_scope(config: SearchServiceConfig) -> str:
    """Identity a search for ``config`` is billed and answered under, as a cache-key component.

    Every credential a request may actually be answered with belongs here, because a cached
    payload must never be replayed for another one:

    - A gateway-routed provider authenticates per request, so the gateway endpoint and token
      identify that hop. SearxNG is excluded: it is always reached at its own endpoint.
    - The provider's own key and base URL travel too. A routed request falls back to them when
      the gateway answers a retryable failure, and that fallback is billed to them, so they
      are part of the effective identity whether or not the gateway is used.
    """
    gateway = config.gateway_config
    scopes: list[str] = []
    if gateway is not None and gateway.use_gateway and config.search_service != "searxng":
        scopes.append(f"gateway:{gateway.gateway_url or ''}:{gateway.auth_token or ''}")
    scopes.append(f"direct:{config.api_key or ''}@{config.api_base or ''}")
    return "|".join(scopes)


def build_search_service(config: SearchServiceConfig, *, bypass_gateway: bool = False) -> SearchService:
    """Build the search client for ``config``.

    Args:
        config: Provider configuration of a single chain hop.
        bypass_gateway: Connect to the provider directly even when the config routes through the gateway.

    Raises:
        SearchConfigError: A credential or endpoint the provider needs is missing.
    """
    provider = config.search_service
    gateway = config.gateway_config

    if provider == "volcengine_doubao":
        from myrm_agent_harness.toolkits.web_search.providers.volcengine_doubao_search import VolcengineDoubaoSearch

        return VolcengineDoubaoSearch(
            api_key=require_api_key(config),
            timeout_seconds=config.timeout_seconds,
            api_base=config.api_base,
        )

    from myrm_agent_harness.toolkits.web_search.providers.litellm_search import LiteLLMSearch

    api_key: str | None
    api_base: str | None
    if provider == "searxng":
        if not config.api_base:
            raise SearchConfigError(
                "SearxNG search requires api_base in SearchServiceConfig (configure via WebUI Settings)",
                config_key="api_base",
            )
        api_key, api_base = config.api_key, config.api_base
    elif gateway is not None and gateway.use_gateway and not bypass_gateway:
        if not gateway.gateway_url or not gateway.auth_token:
            raise SearchConfigError(
                f"{provider} search routed through the gateway requires gateway_url and auth_token",
                config_key="gateway_config",
            )
        api_key, api_base = gateway.auth_token, f"{gateway.gateway_url.rstrip('/')}/{provider}"
    else:
        api_key, api_base = require_api_key(config), config.api_base

    logger.debug("Search service %s ready", provider)
    return LiteLLMSearch(
        search_provider=provider,
        api_key=api_key,
        api_base=api_base,
        timeout_seconds=config.timeout_seconds,
    )
