"""A hung provider must not consume the chain budget.

The real coalescing wait, retry loop and outer cap run; only the network call is faked and the clocks are shrunk
(x0.01) so production ratios hold: per-attempt cap 20 s, coalescing wait 30 s (x2), chain budget 45 s.
"""

from __future__ import annotations

import asyncio
import gc
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest

from myrm_agent_harness.toolkits.web_search.coalescing import search_coalescing as coalescing
from myrm_agent_harness.toolkits.web_search.core.common import SearchResult
from myrm_agent_harness.toolkits.web_search.core.exceptions import AllQueriesFailedError
from myrm_agent_harness.toolkits.web_search.providers import chain as chain_module
from myrm_agent_harness.toolkits.web_search.providers.web_searcher import SearchServiceConfig, WebSearcher

_ATTEMPT_TIMEOUT_SECONDS = 0.2
_COALESCING_WAIT_SECONDS = 0.3
_CHAIN_BUDGET_SECONDS = 0.45
# Keeps the outer cap out of the way so the chain's own timing decides the outcome.
_OUTER_CAP_SECONDS = 5


@dataclass
class _Network:
    """Per-provider behavior (``ok`` | ``hang`` | ``slow_ok`` | ``fail_late``) and request counts."""

    behaviors: dict[str, str] = field(default_factory=dict)
    calls: dict[str, int] = field(default_factory=dict)


class _FakeService:
    def __init__(self, network: _Network, provider: str) -> None:
        self._network = network
        self._provider = provider

    async def search(self, query: str, num_results: int, **_: object) -> list[SearchResult]:
        self._network.calls[self._provider] = self._network.calls.get(self._provider, 0) + 1
        behavior = self._network.behaviors[self._provider]
        if behavior == "hang":
            # What LiteLLM does when the provider never answers: the per-attempt cap fires.
            await asyncio.wait_for(asyncio.sleep(3600), timeout=_ATTEMPT_TIMEOUT_SECONDS)
        elif behavior == "slow_ok":
            await asyncio.sleep(0.25)
        elif behavior == "fail_late":
            await asyncio.sleep(0.5)
            raise ValueError("late provider failure")
        return [SearchResult(title=self._provider, link=f"https://{self._provider}.example/{query}", snippet="s")]


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Network]:
    fake = _Network()

    async def fake_get_service(self: WebSearcher, bypass_gateway: bool = False) -> _FakeService:
        return _FakeService(fake, self.config.search_service)

    monkeypatch.setattr(WebSearcher, "_get_search_service", fake_get_service)
    monkeypatch.setattr(coalescing, "COALESCING_TIMEOUT_SECONDS", _COALESCING_WAIT_SECONDS)
    monkeypatch.setattr(chain_module, "_CHAIN_WALL_CLOCK_SECONDS", _CHAIN_BUDGET_SECONDS)
    chain_module.default_quota_tracker.reset_all()
    coalescing.reset_search_coalescing_state_for_tests()
    yield fake
    coalescing.reset_search_coalescing_state_for_tests()
    chain_module.default_quota_tracker.reset_all()


def _searcher(providers: list[str], *, retries: int = 2) -> WebSearcher:
    members = [
        SearchServiceConfig(
            search_service=slug,
            api_key="key",
            search_max_retries=retries,
            retry_backoff_base_seconds=0.01,
            retry_backoff_max_seconds=0.04,
        )
        for slug in providers
    ]
    head = members[0].model_copy(update={"provider_chain": members, "total_timeout_seconds": _OUTER_CAP_SECONDS})
    return WebSearcher(head)


@pytest.mark.asyncio
async def test_hung_head_provider_hands_over_to_the_next_provider(network: _Network) -> None:
    network.behaviors.update(tavily="hang", perplexity="ok")

    _, documents, error = (await _searcher(["tavily", "perplexity"]).multi_query_parallel_search(["q"], 5))[0]

    assert error is None and documents, "the head provider must not consume the whole chain budget"
    assert network.calls["perplexity"] >= 1


@pytest.mark.asyncio
async def test_last_provider_keeps_the_whole_remaining_budget(network: _Network) -> None:
    network.behaviors.update(tavily="hang", perplexity="slow_ok")

    _, documents, error = (await _searcher(["tavily", "perplexity"]).multi_query_parallel_search(["q"], 5))[0]

    assert error is None and documents, "the final provider answers slower than any non-final allowance"


@pytest.mark.asyncio
async def test_single_provider_hang_reports_a_timeout_not_an_empty_message(network: _Network) -> None:
    network.behaviors.update(tavily="hang")

    with pytest.raises(AllQueriesFailedError) as raised:
        await _searcher(["tavily"]).multi_query_parallel_search(["q"], 5)

    assert "Search request timeout" in str(raised.value)


@pytest.mark.asyncio
async def test_failure_of_a_leader_orphaned_by_the_allowance_is_not_left_unretrieved(network: _Network) -> None:
    network.behaviors.update(tavily="fail_late", perplexity="ok")
    loop = asyncio.get_running_loop()
    reported: list[str] = []
    loop.set_exception_handler(lambda _loop, context: reported.append(str(context.get("message"))))
    try:
        _, _, error = (await _searcher(["tavily", "perplexity"], retries=0).multi_query_parallel_search(["q"], 5))[0]
        await asyncio.sleep(0.8)  # the cut-off head provider fails after the chain has moved on
        gc.collect()
    finally:
        loop.set_exception_handler(None)

    assert error is None
    assert not [message for message in reported if "never retrieved" in message]
