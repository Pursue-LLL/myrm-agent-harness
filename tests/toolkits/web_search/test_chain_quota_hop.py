"""Chain quota/rate-limit hop policy tests."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.web_search.core.common import SearchResult
from myrm_agent_harness.toolkits.web_search.core.error_handling import (
    is_persistent_quota_depleted_error,
    is_quota_or_rate_limit_error,
    is_retryable_search_error,
)
from myrm_agent_harness.toolkits.web_search.core.exceptions import (
    ErrorContext,
    SearchAPIError,
)
from myrm_agent_harness.toolkits.web_search.providers import chain as chain_module
from myrm_agent_harness.toolkits.web_search.providers.chain import (
    _DEFAULT_DEPLETED_COOLDOWN_SECONDS,
    ProviderQuotaStatus,
    ProviderQuotaTracker,
    _should_stop_chain,
    search_provider_chain,
)
from myrm_agent_harness.toolkits.web_search.providers.web_searcher import (
    SearchServiceConfig,
    WebSearcher,
)


def test_quota_error_should_not_stop_chain() -> None:
    exc = Exception("API Error [10406]: quota exhausted")
    assert is_quota_or_rate_limit_error(exc) is True
    assert is_retryable_search_error(exc) is False
    assert _should_stop_chain(exc) is False


def test_timeout_retryable_should_stop_chain() -> None:
    exc = Exception("Connection timeout")
    assert is_quota_or_rate_limit_error(exc) is False
    assert _should_stop_chain(exc) is True


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


def test_search_api_error_with_429_body_should_hop() -> None:
    ctx = ErrorContext(
        query="q",
        status_code=429,
        response_body="10406 quota",
        retryable=False,
    )
    exc = SearchAPIError("limited", context=ctx)
    assert is_quota_or_rate_limit_error(exc) is True
    assert _should_stop_chain(exc) is False


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
    chain = [
        SearchServiceConfig(search_service="tavily", api_key="tvly-key"),
        SearchServiceConfig(search_service="perplexity", api_key="pplx-key"),
    ]
    tracker = ProviderQuotaTracker()
    tracker.mark_depleted("tavily", reason="plan limit exceeded")

    async def fake_search(
        self: WebSearcher,
        query: str,
        num_results: int = 5,
        extra_params_override: dict[str, str | int | bool] | None = None,
    ) -> list[SearchResult]:
        return [SearchResult(title=self.config.search_service, link="https://example.com", snippet=query)]

    monkeypatch.setattr(WebSearcher, "search", fake_search)

    _, winner = await search_provider_chain(chain, "q", 5, quota_tracker=tracker)
    assert winner == "perplexity"

    fake_clock.advance(_DEFAULT_DEPLETED_COOLDOWN_SECONDS)
    _, winner = await search_provider_chain(chain, "q", 5, quota_tracker=tracker)
    assert winner == "tavily"


def test_browser_run_telemetry_bandwidth_and_watchdog() -> None:
    """测试 BrowserRunTelemetry 带宽度量与看门狗计数"""
    import time

    from myrm_agent_harness.toolkits.browser.observability import (
        BrowserObservability,
        BrowserRunTelemetry,
        RecordingConfig,
    )

    telemetry = BrowserRunTelemetry()
    telemetry.record_compute(12.5)
    telemetry.record_transfer(1024)
    telemetry.record_request(success=True, bytes_transferred=2048)
    telemetry.record_request(success=False, bytes_transferred=512)

    snap = telemetry.snapshot()
    assert snap["active_compute_seconds"] == 12.5
    assert snap["total_bytes_transferred"] == 3584
    assert snap["request_count"] == 2
    assert snap["failed_request_count"] == 1

    obs = BrowserObservability(RecordingConfig(), telemetry=telemetry)
    start_time = time.monotonic() - 200.0
    telemetry.last_activity_time = start_time
    safe = obs.check_action_watchdog(action_start_time=start_time, timeout_seconds=180.0)
    assert safe is False
    assert obs.telemetry.watchdog_tripped_count == 1
