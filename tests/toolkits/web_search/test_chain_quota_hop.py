"""Chain quota/rate-limit hop policy tests."""

from __future__ import annotations

from myrm_agent_harness.toolkits.web_search.core.error_handling import (
    is_persistent_quota_depleted_error,
    is_quota_or_rate_limit_error,
    is_retryable_search_error,
)
from myrm_agent_harness.toolkits.web_search.core.exceptions import (
    ErrorContext,
    SearchAPIError,
)
from myrm_agent_harness.toolkits.web_search.providers.chain import (
    ProviderQuotaStatus,
    ProviderQuotaTracker,
    _should_stop_chain,
    search_provider_chain,
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

