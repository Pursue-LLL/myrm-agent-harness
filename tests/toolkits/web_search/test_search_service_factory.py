"""build_search_service: provider wiring, credential requirements, gateway routing and credential identity.

[INPUT]
- web_search.providers.search_service_factory::build_search_service, credential_scope_digest
- web_search.providers.web_searcher::SearchServiceConfig, WebSearcher
- core.config.gateway::ToolGatewayConfig

[POS]
Guards which client a config yields, which credentials are mandatory, that a half-configured gateway is
rejected as a config error, and that the cache and the quota cooldown address one credential the same way.
"""

import pytest

from myrm_agent_harness.core.config.gateway import ToolGatewayConfig
from myrm_agent_harness.toolkits.web_search.coalescing.search_coalescing import credential_fingerprint
from myrm_agent_harness.toolkits.web_search.core.exceptions import SearchConfigError
from myrm_agent_harness.toolkits.web_search.providers.chain import quota_tracker_key
from myrm_agent_harness.toolkits.web_search.providers.litellm_search import LiteLLMSearch
from myrm_agent_harness.toolkits.web_search.providers.search_service_factory import (
    build_search_service,
    credential_scope_digest,
    describe_credential_scope,
)
from myrm_agent_harness.toolkits.web_search.providers.volcengine_doubao_search import VolcengineDoubaoSearch
from myrm_agent_harness.toolkits.web_search.providers.web_searcher import SearchServiceConfig, WebSearcher

_GATEWAY = ToolGatewayConfig(use_gateway=True, gateway_url="https://gw.example/relay/", auth_token="gw-token")


def _config(
    provider: str,
    *,
    api_key: str | None = None,
    api_base: str | None = None,
    gateway_config: ToolGatewayConfig | None = None,
) -> SearchServiceConfig:
    return SearchServiceConfig(
        search_service=provider, api_key=api_key, api_base=api_base, gateway_config=gateway_config
    )


def test_litellm_provider_gets_its_own_key_and_base() -> None:
    service = build_search_service(_config("tavily", api_key="k", api_base="https://api.example"))

    assert isinstance(service, LiteLLMSearch)
    assert (service.search_provider, service.api_key, service.api_base) == ("tavily", "k", "https://api.example")


def test_litellm_provider_without_key_is_a_config_error() -> None:
    with pytest.raises(SearchConfigError, match="requires API key"):
        build_search_service(_config("tavily"))


def test_searxng_needs_api_base_but_no_key() -> None:
    service = build_search_service(_config("searxng", api_base="http://localhost:8081"))

    assert isinstance(service, LiteLLMSearch)
    assert service.api_key is None
    with pytest.raises(SearchConfigError, match="api_base"):
        build_search_service(_config("searxng"))


def test_volcengine_uses_the_native_client() -> None:
    assert isinstance(build_search_service(_config("volcengine_doubao", api_key="k")), VolcengineDoubaoSearch)
    with pytest.raises(SearchConfigError, match="requires API key"):
        build_search_service(_config("volcengine_doubao"))


def test_gateway_routing_overrides_base_and_key() -> None:
    service = build_search_service(_config("tavily", api_key="byok", gateway_config=_GATEWAY))

    assert isinstance(service, LiteLLMSearch)
    assert (service.api_base, service.api_key) == ("https://gw.example/relay/tavily", "gw-token")


def test_bypass_gateway_falls_back_to_the_users_own_key() -> None:
    service = build_search_service(_config("tavily", api_key="byok", gateway_config=_GATEWAY), bypass_gateway=True)

    assert isinstance(service, LiteLLMSearch)
    assert (service.api_base, service.api_key) == (None, "byok")
    with pytest.raises(SearchConfigError, match="requires API key"):
        build_search_service(_config("tavily", gateway_config=_GATEWAY), bypass_gateway=True)


def test_searxng_ignores_the_gateway() -> None:
    service = build_search_service(_config("searxng", api_base="http://localhost:8081", gateway_config=_GATEWAY))

    assert isinstance(service, LiteLLMSearch)
    assert service.api_base == "http://localhost:8081"


@pytest.mark.parametrize(
    "gateway",
    [
        ToolGatewayConfig(use_gateway=True, gateway_url=None, auth_token="t"),
        ToolGatewayConfig(use_gateway=True, gateway_url="https://gw.example", auth_token=None),
        ToolGatewayConfig(use_gateway=True, gateway_url="", auth_token="t"),
    ],
)
def test_half_configured_gateway_is_a_config_error(gateway: ToolGatewayConfig) -> None:
    with pytest.raises(SearchConfigError, match="gateway_url and auth_token"):
        build_search_service(_config("tavily", api_key="byok", gateway_config=gateway))


@pytest.mark.asyncio
async def test_searcher_caches_the_routed_client_but_not_the_bypass_client() -> None:
    searcher = WebSearcher(_config("tavily", api_key="byok", gateway_config=_GATEWAY))

    routed = await searcher._get_search_service()
    direct = await searcher._get_search_service(bypass_gateway=True)

    assert direct is not routed
    assert searcher._search_service is routed
    assert await searcher._get_search_service() is routed


def test_the_credential_digest_names_the_credential_without_the_provider_slug() -> None:
    """The caller adds the slug, so one credential keeps one digest across providers.

    Both key builders already prepend the slug, so a digest that folded it in would double it in the cache key and
    let the cooldown scope drift from the cache identity as soon as the two callers composed their keys differently.
    """
    keyed_tavily = credential_scope_digest(_config("tavily", api_key="key-a"))
    keyed_brave = credential_scope_digest(_config("brave", api_key="key-a"))

    assert keyed_tavily == keyed_brave
    assert credential_scope_digest(_config("tavily", api_key="key-a")) == keyed_tavily
    assert credential_scope_digest(_config("tavily", api_key="key-b")) != keyed_tavily
    assert credential_fingerprint(describe_credential_scope(_config("tavily", api_key="key-a"))) == keyed_tavily


def test_the_cache_and_the_cooldown_address_one_credential_the_same_way() -> None:
    """A cached payload and a cooldown are keyed by the credential the factory names, so the two layers agree.

    They diverged once, when a rotated key missed the cache but stayed benched under the old account's cooldown.
    Both comparisons must flip together for that to happen again, so a re-derived identity on either side is caught.
    """
    account_a = _config("tavily", api_key="key-a")
    account_a_again = _config("tavily", api_key="key-a")
    rotated = _config("tavily", api_key="key-b")

    assert credential_scope_digest(account_a) == credential_scope_digest(account_a_again)
    assert credential_scope_digest(account_a) != credential_scope_digest(rotated)
    assert quota_tracker_key(account_a) == quota_tracker_key(account_a_again)
    assert quota_tracker_key(account_a) != quota_tracker_key(rotated)
    # The cooldown key is the cache identity under the provider slug, never a second identity of its own.
    assert quota_tracker_key(account_a) == f"tavily:{credential_scope_digest(account_a)}"
