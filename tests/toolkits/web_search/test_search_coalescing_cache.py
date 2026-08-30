"""Tests for search coalescing TTL cache eligibility."""

import asyncio

import pytest

from myrm_agent_harness.toolkits.web_search.coalescing import search_coalescing as sc
from myrm_agent_harness.toolkits.web_search.coalescing.search_coalescing import (
    await_coalesced_search,
    has_cacheable_search_results,
    reset_search_coalescing_state_for_tests,
    slice_search_results,
)
from myrm_agent_harness.toolkits.web_search.core.common import SearchResult


@pytest.fixture(autouse=True)
def _clear_coalescing_state():
    reset_search_coalescing_state_for_tests()
    yield
    reset_search_coalescing_state_for_tests()


def test_has_cacheable_search_results_requires_usable_link() -> None:
    assert not has_cacheable_search_results([])
    assert not slice_search_results([SearchResult(link="https://x.com", title="T", snippet="S")], 0)
    assert not has_cacheable_search_results(
        [SearchResult(link="", title="Empty", snippet="S")]
    )
    assert not has_cacheable_search_results(
        [SearchResult(link="https://err.com", title="Err", snippet="S", is_error=True)]
    )
    assert has_cacheable_search_results(
        [SearchResult(link="https://ok.com", title="OK", snippet="S")]
    )


@pytest.mark.asyncio
async def test_empty_search_results_are_not_ttl_cached() -> None:
    call_count = 0

    async def fetch() -> list[SearchResult]:
        nonlocal call_count
        call_count += 1
        return []

    cache_key = "test:empty-not-cached:10:"

    first = await await_coalesced_search(
        cache_key, 10, 5, fetch, log_label="empty-first"
    )
    second = await await_coalesced_search(
        cache_key, 10, 5, fetch, log_label="empty-second"
    )

    assert first == []
    assert second == []
    assert call_count == 2
    assert sc._search_cache.get(cache_key) is None


@pytest.mark.asyncio
async def test_empty_search_results_still_coalesce_in_flight() -> None:
    call_count = 0
    release = asyncio.Event()

    async def fetch() -> list[SearchResult]:
        nonlocal call_count
        call_count += 1
        await release.wait()
        return []

    cache_key = "test:empty-coalesce:10:"

    first_task = asyncio.create_task(
        await_coalesced_search(cache_key, 10, 5, fetch, log_label="empty-a")
    )
    await asyncio.sleep(0.01)
    second_task = asyncio.create_task(
        await_coalesced_search(cache_key, 10, 5, fetch, log_label="empty-b")
    )
    release.set()

    first, second = await asyncio.gather(first_task, second_task)

    assert first == []
    assert second == []
    assert call_count == 1
    assert sc._search_cache.get(cache_key) is None


@pytest.mark.asyncio
async def test_usable_search_results_remain_ttl_cached() -> None:
    call_count = 0

    async def fetch() -> list[SearchResult]:
        nonlocal call_count
        call_count += 1
        return [SearchResult(link="https://cached.com", title="Cached", snippet="S")]

    cache_key = "test:usable-cached:10:"

    await await_coalesced_search(cache_key, 10, 5, fetch, log_label="usable-first")
    results = await await_coalesced_search(
        cache_key, 10, 5, fetch, log_label="usable-second"
    )

    assert call_count == 1
    assert len(results) == 1
    assert results[0].link == "https://cached.com"
    assert sc._search_cache.get(cache_key) is not None


@pytest.mark.asyncio
async def test_error_only_search_results_are_not_ttl_cached() -> None:
    call_count = 0

    async def fetch() -> list[SearchResult]:
        nonlocal call_count
        call_count += 1
        return [
            SearchResult(
                link="https://err.com",
                title="Err",
                snippet="provider failed",
                is_error=True,
            )
        ]

    cache_key = "test:error-not-cached:10:"

    first = await await_coalesced_search(
        cache_key, 10, 5, fetch, log_label="error-first"
    )
    second = await await_coalesced_search(
        cache_key, 10, 5, fetch, log_label="error-second"
    )

    assert len(first) == 1
    assert first[0].is_error is True
    assert len(second) == 1
    assert call_count == 2
    assert sc._search_cache.get(cache_key) is None
