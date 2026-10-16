"""Chain failover policy tests: quota cooldowns, outage hops and query-independent failure classification."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.web_search.core.common import SearchResult
from myrm_agent_harness.toolkits.web_search.core.error_handling import (
    is_persistent_quota_depleted_error,
    is_quota_or_rate_limit_error,
    is_retryable_search_error,
)
from myrm_agent_harness.toolkits.web_search.core.exceptions import (
    AllQueriesFailedError,
    ErrorContext,
    SearchAPIError,
)
from myrm_agent_harness.toolkits.web_search.core.metrics import WebSearchMetrics
from myrm_agent_harness.toolkits.web_search.providers import chain as chain_module
from myrm_agent_harness.toolkits.web_search.providers.chain import (
    _DEFAULT_DEPLETED_COOLDOWN_SECONDS,
    ProviderQuotaStatus,
    ProviderQuotaTracker,
    search_provider_chain,
)
from myrm_agent_harness.toolkits.web_search.providers.web_searcher import (
    SearchServiceConfig,
    WebSearcher,
)


def _two_provider_chain() -> list[SearchServiceConfig]:
    return [
        SearchServiceConfig(search_service="tavily", api_key="tvly-key"),
        SearchServiceConfig(search_service="perplexity", api_key="pplx-key"),
    ]


def _install_search(monkeypatch: pytest.MonkeyPatch, failures: dict[str, Exception]) -> list[str]:
    """Patch ``WebSearcher.search``: providers in ``failures`` raise, the others answer; returns the call log."""
    calls: list[str] = []

    async def fake_search(
        self: WebSearcher,
        query: str,
        num_results: int = 5,
        extra_params_override: dict[str, str | int | bool] | None = None,
    ) -> list[SearchResult]:
        provider = self.config.search_service
        calls.append(provider)
        if provider in failures:
            raise failures[provider]
        return [SearchResult(title=provider, link="https://example.com", snippet=query)]

    monkeypatch.setattr(WebSearcher, "search", fake_search)
    return calls


def test_quota_error_skips_intra_hop_retry() -> None:
    exc = Exception("API Error [10406]: quota exhausted")
    assert is_quota_or_rate_limit_error(exc) is True
    assert is_retryable_search_error(exc) is False


def test_search_api_error_context_body_quota_detection() -> None:
    ctx = ErrorContext(
        query="q",
        status_code=500,
        response_body="10406 quota exhausted",
        retryable=False,
    )
    exc = SearchAPIError("limited", context=ctx)
    assert is_quota_or_rate_limit_error(exc) is True


def test_quota_detects_http_status_on_exception() -> None:
    exc = Exception("provider error")
    exc.http_status = 429
    assert is_quota_or_rate_limit_error(exc) is True


def test_search_api_error_with_429_body_is_rate_limited() -> None:
    ctx = ErrorContext(
        query="q",
        status_code=429,
        response_body="10406 quota",
        retryable=False,
    )
    exc = SearchAPIError("limited", context=ctx)
    assert is_quota_or_rate_limit_error(exc) is True


@pytest.mark.parametrize(
    "query",
    [
        "how to raise aws service quota",
        "openai usage limit explained",
        "http 429 too many requests meaning",
        "what does payment required 402 mean",
        "what to do when out of credits",
        "monthly limit vs credit limit vs plan limit",
    ],
)
def test_query_text_never_reads_as_a_quota_or_rate_limit_signal(query: str) -> None:
    exc = SearchAPIError(
        "Search request timeout",
        context=ErrorContext(query=query, error_code="TimeoutError", retryable=True),
    )
    assert query not in str(exc)
    assert is_quota_or_rate_limit_error(exc) is False
    assert is_persistent_quota_depleted_error(exc) is False


def test_provider_reply_still_marks_quota_and_rate_limit() -> None:
    exhausted = SearchAPIError(
        "Search request failed: Search service quota exceeded — upgrade your plan or use a different API key",
        context=ErrorContext(
            query="weather", status_code=432, response_body="This request exceeds your plan's set usage limit"
        ),
    )
    assert is_persistent_quota_depleted_error(exhausted) is True
    assert is_quota_or_rate_limit_error(exhausted) is True

    throttled = SearchAPIError(
        "Search request failed: Search service rate limit exceeded (429 Too Many Requests)",
        context=ErrorContext(query="weather", status_code=429),
    )
    assert is_quota_or_rate_limit_error(throttled) is True
    assert is_persistent_quota_depleted_error(throttled) is False


def test_persistent_quota_depleted_distinction() -> None:
    # 402 Payment Required -> Persistent
    exc_402 = Exception("Payment required")
    exc_402.status_code = 402
    assert is_persistent_quota_depleted_error(exc_402) is True

    # Quota exceeded text -> Persistent
    exc_quota = Exception("Monthly usage limit reached: quota_exceeded")
    assert is_persistent_quota_depleted_error(exc_quota) is True

    # Pure transient rate limit -> Not persistent
    exc_transient = Exception("Too many requests: rate limit 10/s")
    assert is_persistent_quota_depleted_error(exc_transient) is False
    assert is_quota_or_rate_limit_error(exc_transient) is True


def test_provider_quota_tracker_workflow() -> None:
    tracker = ProviderQuotaTracker()

    # Initial state: healthy
    status, reason = tracker.get_status("brave")
    assert status == ProviderQuotaStatus.HEALTHY
    assert reason == ""

    # Mark rate limited (cooldown 1s)
    tracker.mark_rate_limited("brave", cooldown_seconds=0.05, reason="429 rate limit")
    status, reason = tracker.get_status("brave")
    assert status == ProviderQuotaStatus.RATE_LIMITED
    assert "429 rate limit" in reason

    # Mark depleted
    tracker.mark_depleted("brave", reason="Monthly quota depleted")
    status, reason = tracker.get_status("brave")
    assert status == ProviderQuotaStatus.DEPLETED
    assert "Monthly quota depleted" in reason

    # Reset provider
    tracker.reset_provider("brave")
    status, _ = tracker.get_status("brave")
    assert status == ProviderQuotaStatus.HEALTHY


class _FakeClock:
    """Replaces the `time` module inside chain.py so cooldown expiry is deterministic."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    clock = _FakeClock()
    monkeypatch.setattr(chain_module, "time", clock)
    return clock


def test_depleted_provider_recovers_after_cooldown(fake_clock: _FakeClock) -> None:
    tracker = ProviderQuotaTracker()
    tracker.mark_depleted("tavily", reason="plan limit exceeded")

    fake_clock.advance(_DEFAULT_DEPLETED_COOLDOWN_SECONDS - 1)
    assert tracker.get_status("tavily") == (ProviderQuotaStatus.DEPLETED, "plan limit exceeded")

    fake_clock.advance(1)
    assert tracker.get_status("tavily") == (ProviderQuotaStatus.HEALTHY, "")

    tracker.mark_depleted("tavily", reason="still exhausted")
    assert tracker.get_status("tavily") == (ProviderQuotaStatus.DEPLETED, "still exhausted")


def test_rate_limited_provider_recovers_after_cooldown(fake_clock: _FakeClock) -> None:
    tracker = ProviderQuotaTracker()
    tracker.mark_rate_limited("brave", cooldown_seconds=5.0, reason="429")

    fake_clock.advance(4.9)
    assert tracker.get_status("brave") == (ProviderQuotaStatus.RATE_LIMITED, "429")

    fake_clock.advance(0.2)
    assert tracker.get_status("brave") == (ProviderQuotaStatus.HEALTHY, "")


@pytest.mark.asyncio
async def test_chain_probes_depleted_primary_again_after_cooldown(
    fake_clock: _FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    chain = _two_provider_chain()
    tracker = ProviderQuotaTracker()
    tracker.mark_depleted("tavily", reason="plan limit exceeded")
    _install_search(monkeypatch, {})

    _, winner = await search_provider_chain(chain, "q", 5, quota_tracker=tracker)
    assert winner == "perplexity"

    fake_clock.advance(_DEFAULT_DEPLETED_COOLDOWN_SECONDS)
    _, winner = await search_provider_chain(chain, "q", 5, quota_tracker=tracker)
    assert winner == "tavily"


_OUTAGE_FAILURES = {
    "http_502": SearchAPIError(
        "Search service unavailable (502 Bad Gateway)", ErrorContext(status_code=502, retryable=True)
    ),
    "http_503": SearchAPIError(
        "Search service temporarily unavailable (503 Service Unavailable)",
        ErrorContext(status_code=503, retryable=True),
    ),
    "http_504": SearchAPIError(
        "Search service timeout (504 Gateway Timeout)", ErrorContext(status_code=504, retryable=True)
    ),
    "request_timeout": SearchAPIError(
        "Search request timeout", ErrorContext(error_code="TimeoutError", retryable=True)
    ),
    "cannot_connect": SearchAPIError(
        "Cannot connect to search service", ErrorContext(error_code="ConnectionError", retryable=True)
    ),
    "bare_timeout": TimeoutError("Request timed out"),
    "bare_connection_refused": ConnectionError("Connection refused"),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", _OUTAGE_FAILURES.values(), ids=_OUTAGE_FAILURES.keys())
async def test_chain_hops_past_a_provider_outage(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    calls = _install_search(monkeypatch, {"tavily": failure})
    tracker = ProviderQuotaTracker()
    metrics = WebSearchMetrics()

    _, winner = await search_provider_chain(_two_provider_chain(), "weather", 5, metrics=metrics, quota_tracker=tracker)

    assert winner == "perplexity"
    assert calls == ["tavily", "perplexity"]
    assert metrics.chain_hop_count == 1
    # An outage is not a quota event: the provider stays eligible for the very next call.
    assert tracker.get_status("tavily") == (ProviderQuotaStatus.HEALTHY, "")


@pytest.mark.asyncio
async def test_chain_fails_after_trying_every_provider_during_a_full_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_search(
        monkeypatch,
        {"tavily": TimeoutError("Request timed out"), "perplexity": ConnectionError("Connection refused")},
    )
    metrics = WebSearchMetrics()

    with pytest.raises(AllQueriesFailedError):
        await search_provider_chain(
            _two_provider_chain(), "weather", 5, metrics=metrics, quota_tracker=ProviderQuotaTracker()
        )

    assert calls == ["tavily", "perplexity"]
    assert metrics.chain_hop_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    ["how to raise aws service quota", "http 429 too many requests meaning", "out of credits meaning"],
)
async def test_outage_on_a_keyword_query_does_not_blacklist_the_provider(
    monkeypatch: pytest.MonkeyPatch, query: str
) -> None:
    timeout = SearchAPIError(
        "Search request timeout", ErrorContext(query=query, error_code="TimeoutError", retryable=True)
    )
    failures: dict[str, Exception] = {"tavily": timeout}
    _install_search(monkeypatch, failures)
    tracker = ProviderQuotaTracker()

    await search_provider_chain(_two_provider_chain(), query, 5, quota_tracker=tracker)
    assert tracker.get_status("tavily") == (ProviderQuotaStatus.HEALTHY, "")

    failures.clear()  # the outage ends; an unrelated query must reach the primary again
    _, winner = await search_provider_chain(_two_provider_chain(), "weather", 5, quota_tracker=tracker)
    assert winner == "tavily"


@pytest.mark.asyncio
async def test_quota_failure_still_puts_the_provider_on_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    exhausted = SearchAPIError(
        "Search request failed: Search service quota exceeded — upgrade your plan or use a different API key",
        ErrorContext(
            query="weather", status_code=432, response_body="This request exceeds your plan's set usage limit"
        ),
    )
    _install_search(monkeypatch, {"tavily": exhausted})
    tracker = ProviderQuotaTracker()

    _, winner = await search_provider_chain(_two_provider_chain(), "weather", 5, quota_tracker=tracker)

    assert winner == "perplexity"
    assert tracker.get_status("tavily")[0] == ProviderQuotaStatus.DEPLETED
