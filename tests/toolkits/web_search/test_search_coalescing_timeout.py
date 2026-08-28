"""Tests for search coalescing timeout and lock retention."""

import asyncio

import pytest

from myrm_agent_harness.toolkits.web_search.common import SearchResult
from myrm_agent_harness.toolkits.web_search import search_coalescing as sc
from myrm_agent_harness.toolkits.web_search.search_coalescing import (
    await_coalesced_search,
    reset_search_coalescing_state_for_tests,
)


@pytest.fixture(autouse=True)
def _clear_coalescing_state():
    reset_search_coalescing_state_for_tests()
    yield
    reset_search_coalescing_state_for_tests()


@pytest.mark.asyncio
async def test_coalesce_timeout_retries_without_direct_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sc, "COALESCING_TIMEOUT_SECONDS", 0.15)

    call_count = 0

    async def fetch() -> list[SearchResult]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            await asyncio.sleep(0.5)
        return [SearchResult(link="https://ok.com", title="OK", snippet="S")]

    cache_key = "test:timeout-retry:10:"
    results = await await_coalesced_search(
        cache_key,
        bucketed_limit=10,
        caller_limit=5,
        fetch=fetch,
        log_label="timeout-retry",
    )

    assert call_count == 2
    assert len(results) == 1
    assert results[0].link == "https://ok.com"


@pytest.mark.asyncio
async def test_coalesce_timeout_concurrent_waiters_bounded_api_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sc, "COALESCING_TIMEOUT_SECONDS", 0.15)

    call_count = 0

    async def fetch() -> list[SearchResult]:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.4 if call_count == 1 else 0.02)
        return [SearchResult(link=f"https://r{call_count}.com", title="R", snippet="S")]

    cache_key = "test:timeout-concurrent:10:"

    outcomes = await asyncio.gather(
        await_coalesced_search(cache_key, 10, 5, fetch, log_label="q1"),
        await_coalesced_search(cache_key, 10, 5, fetch, log_label="q2"),
        return_exceptions=True,
    )

    assert all(not isinstance(item, BaseException) for item in outcomes)
    # First leader may increment before cancel; bounded to a small constant (not unbounded dup).
    assert call_count <= 3


@pytest.mark.asyncio
async def test_coalesce_lock_retention_keeps_held_locks() -> None:
    held_key = "held"
    idle_key = "idle"
    held_lock = asyncio.Lock()
    await held_lock.acquire()
    sc._coalesce_locks[held_key] = held_lock
    sc._coalesce_locks[idle_key] = asyncio.Lock()

    for i in range(sc._MAX_COALESCE_LOCKS + 2):
        sc._coalesce_lock_for(f"key-{i}")

    assert held_key in sc._coalesce_locks
    assert idle_key not in sc._coalesce_locks
    held_lock.release()
