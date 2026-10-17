"""A provider that answers with no results has not answered: the chain hands over to the next provider.

Aggregators such as SearXNG reply HTTP 200 with an empty list while their upstream engines are blocked, so the
emptiness is the only failure signal the chain ever sees.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from myrm_agent_harness.toolkits.web_search.coalescing import search_coalescing as coalescing
from myrm_agent_harness.toolkits.web_search.core.common import SearchResult
from myrm_agent_harness.toolkits.web_search.providers import chain as chain_module
from myrm_agent_harness.toolkits.web_search.providers.chain import (
    ProviderQuotaStatus,
    ProviderQuotaTracker,
    search_provider_chain,
)
from myrm_agent_harness.toolkits.web_search.providers.web_searcher import SearchServiceConfig, WebSearcher


def _chain(*providers: str) -> list[SearchServiceConfig]:
    return [SearchServiceConfig(search_service=slug, api_key="key") for slug in providers]


def _answer(provider: str, query: str) -> list[SearchResult]:
    return [SearchResult(title=provider, link=f"https://{provider}.example/{query}", snippet="s")]


def _install_search(
    monkeypatch: pytest.MonkeyPatch, *, empty: frozenset[str] = frozenset(), failing: frozenset[str] = frozenset()
) -> list[str]:
    """Patch ``WebSearcher.search``: ``failing`` providers raise, ``empty`` ones return nothing, the rest answer."""
    calls: list[str] = []

    async def fake_search(
        self: WebSearcher,
        query: str,
        num_results: int = 5,
        extra_params_override: dict[str, str | int | bool] | None = None,
    ) -> list[SearchResult]:
        provider = self.config.search_service
        calls.append(provider)
        if provider in failing:
            raise TimeoutError("Request timed out")
        return [] if provider in empty else _answer(provider, query)

    monkeypatch.setattr(WebSearcher, "search", fake_search)
    return calls


@pytest.mark.asyncio
async def test_empty_head_hands_over_to_the_next_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_search(monkeypatch, empty=frozenset({"searxng"}))
    tracker = ProviderQuotaTracker()

    results, winner = await search_provider_chain(_chain("searxng", "brave"), "q", 5, quota_tracker=tracker)

    assert winner == "brave" and results
    assert calls == ["searxng", "brave"]
    # No results is a property of the query as much as of the provider, so it never puts the provider on cooldown.
    assert tracker.get_status("searxng") == (ProviderQuotaStatus.HEALTHY, "")


@pytest.mark.asyncio
async def test_every_provider_empty_ends_as_an_empty_answer_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_search(monkeypatch, empty=frozenset({"searxng", "brave"}))

    results, winner = await search_provider_chain(
        _chain("searxng", "brave"), "q", 5, quota_tracker=ProviderQuotaTracker()
    )

    assert results == [] and winner == "brave"
    assert calls == ["searxng", "brave"]


@pytest.mark.asyncio
async def test_empty_answer_survives_a_later_provider_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_search(monkeypatch, empty=frozenset({"searxng"}), failing=frozenset({"brave"}))

    results, winner = await search_provider_chain(
        _chain("searxng", "brave"), "q", 5, quota_tracker=ProviderQuotaTracker()
    )

    assert results == [] and winner == "searxng", "an empty answer is still an answer; the failure must not replace it"
    assert calls == ["searxng", "brave"]


@pytest.mark.asyncio
async def test_empty_answer_after_an_earlier_failure_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_search(monkeypatch, empty=frozenset({"brave"}), failing=frozenset({"searxng"}))

    results, winner = await search_provider_chain(
        _chain("searxng", "brave"), "q", 5, quota_tracker=ProviderQuotaTracker()
    )

    assert results == [] and winner == "brave"
    assert calls == ["searxng", "brave"]


@pytest.mark.asyncio
async def test_single_provider_chain_returns_its_empty_answer_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_search(monkeypatch, empty=frozenset({"searxng"}))

    results, winner = await search_provider_chain(_chain("searxng"), "q", 5, quota_tracker=ProviderQuotaTracker())

    assert results == [] and winner == "searxng"
    assert calls == ["searxng"]


class _FakeService:
    def __init__(self, provider: str, calls: list[str]) -> None:
        self._provider = provider
        self._calls = calls

    async def search(self, query: str, num_results: int, **_: object) -> list[SearchResult]:
        self._calls.append(self._provider)
        return [] if self._provider == "searxng" else _answer(self._provider, query)


@pytest.fixture
def service_calls(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    calls: list[str] = []

    async def fake_get_service(self: WebSearcher, bypass_gateway: bool = False) -> _FakeService:
        return _FakeService(self.config.search_service, calls)

    monkeypatch.setattr(WebSearcher, "_get_search_service", fake_get_service)
    chain_module.default_quota_tracker.reset_all()
    coalescing.reset_search_coalescing_state_for_tests()
    yield calls
    coalescing.reset_search_coalescing_state_for_tests()
    chain_module.default_quota_tracker.reset_all()


@pytest.mark.asyncio
async def test_blocked_aggregator_does_not_leave_the_user_without_an_answer(service_calls: list[str]) -> None:
    members = _chain("searxng", "brave")
    searcher = WebSearcher(members[0].model_copy(update={"provider_chain": members}))

    _, documents, error = (await searcher.multi_query_parallel_search(["empty head handover"], 5))[0]

    assert error is None and documents
    assert service_calls == ["searxng", "brave"]
