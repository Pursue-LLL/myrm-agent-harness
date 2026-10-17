"""A quota cooldown belongs to the credentials that earned it, not to the provider slug.

One provider slug can name several billable accounts (a second key, or the replacement key an
operator installs right after a search failed for a wrong one), and the chain's contract is
priority-ordered failover. Benching a slug therefore benches credentials that never failed and
silently demotes them behind a lower-priority provider for the whole cooldown.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from myrm_agent_harness.core.config.gateway import ToolGatewayConfig
from myrm_agent_harness.toolkits.web_search.core.common import SearchResult
from myrm_agent_harness.toolkits.web_search.providers.chain import (
    ProviderQuotaStatus,
    ProviderQuotaTracker,
    quota_tracker_key,
    search_provider_chain,
)
from myrm_agent_harness.toolkits.web_search.providers.web_searcher import (
    SearchServiceConfig,
    WebSearcher,
)


def _provider(slug: str, key: str, *, gateway: ToolGatewayConfig | None = None) -> SearchServiceConfig:
    return SearchServiceConfig(search_service=slug, api_key=key, gateway_config=gateway, search_max_retries=0)


@dataclass
class _Probe:
    """Fake provider layer: it answers per API key and records which keys were actually contacted."""

    contacted: list[str] = field(default_factory=list)
    exhausted: set[str] = field(default_factory=set)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        probe = self

        async def fake_search(
            self: WebSearcher,
            query: str,
            num_results: int = 5,
            extra_params_override: dict[str, str | int | bool] | None = None,
        ) -> list[SearchResult]:
            key = self.config.api_key or self.config.api_base or ""
            probe.contacted.append(key)
            if key in probe.exhausted:
                exc = RuntimeError("402 Payment Required: quota exhausted")
                exc.status_code = 402  # type: ignore[attr-defined]
                raise exc
            return [SearchResult(title=key, link="https://example.com", snippet=query)]

        monkeypatch.setattr(WebSearcher, "search", fake_search)


@pytest.fixture()
def probe(monkeypatch: pytest.MonkeyPatch) -> _Probe:
    fake = _Probe()
    fake.install(monkeypatch)
    return fake


@pytest.mark.asyncio
async def test_exhausted_account_does_not_bench_a_second_account_on_the_same_slug(probe: _Probe) -> None:
    """Two paid accounts on one slug: exhausting one leaves the other its priority."""
    probe.exhausted.add("acct-a")
    account_a = _provider("tavily", "acct-a")
    account_b = _provider("tavily", "acct-b")
    brave = _provider("brave", "brave-key")
    tracker = ProviderQuotaTracker()

    _, winner = await search_provider_chain([account_a, account_b], "q1", 5, quota_tracker=tracker)
    assert probe.contacted == ["acct-a", "acct-b"]  # A is out of quota, B answers
    assert winner == "tavily"

    probe.contacted.clear()
    # A is now benched. Its sibling must keep priority 1: benching the slug would send the next
    # query to brave even though B was never asked and is perfectly healthy.
    _, winner = await search_provider_chain([account_b, brave], "q2", 5, quota_tracker=tracker)
    assert probe.contacted == ["acct-b"]
    assert winner == "tavily"


@pytest.mark.asyncio
async def test_rotating_the_key_restores_the_provider_before_the_backup(probe: _Probe) -> None:
    """Replacing a rejected key is the recovery path: the new key must reach the provider at once."""
    probe.exhausted.add("old-key")
    old = _provider("tavily", "old-key")
    brave = _provider("brave", "brave-key")
    tracker = ProviderQuotaTracker()

    _, winner = await search_provider_chain([old, brave], "q1", 5, quota_tracker=tracker)
    assert probe.contacted == ["old-key", "brave-key"]
    assert winner == "brave"

    probe.contacted.clear()
    rotated = _provider("tavily", "new-key")  # the operator fixed the key in Settings
    _, winner = await search_provider_chain([rotated, brave], "q2", 5, quota_tracker=tracker)
    assert probe.contacted == ["new-key"]  # the fixed key is tried first, and it is enough
    assert winner == "tavily"


def test_the_exhausted_credential_itself_stays_benched() -> None:
    """Scoping must not lose the cooldown it recorded: the credential that failed stays out."""
    tracker = ProviderQuotaTracker()
    account_a = _provider("tavily", "acct-a")
    account_b = _provider("tavily", "acct-b")

    tracker.mark_depleted(quota_tracker_key(account_a), reason="402")

    assert tracker.get_status(quota_tracker_key(account_a)) == (ProviderQuotaStatus.DEPLETED, "402")
    assert tracker.get_status(quota_tracker_key(account_b)) == (ProviderQuotaStatus.HEALTHY, "")


def test_a_gateway_token_is_part_of_the_cooldown_scope() -> None:
    """Two agents behind different gateway tokens draw on different quota, so their cooldowns differ."""
    tracker = ProviderQuotaTracker()
    first = _provider(
        "tavily",
        "key",
        gateway=ToolGatewayConfig(use_gateway=True, gateway_url="https://gw.example", auth_token="vk-a"),
    )
    second = first.model_copy(
        update={
            "gateway_config": ToolGatewayConfig(use_gateway=True, gateway_url="https://gw.example", auth_token="vk-b")
        }
    )

    tracker.mark_depleted(quota_tracker_key(first), reason="402")

    assert tracker.get_status(quota_tracker_key(second)) == (ProviderQuotaStatus.HEALTHY, "")
