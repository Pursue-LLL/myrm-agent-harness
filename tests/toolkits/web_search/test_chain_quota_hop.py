"""Chain quota/rate-limit hop policy tests."""

from __future__ import annotations

from myrm_agent_harness.toolkits.web_search.core.error_handling import (
    is_quota_or_rate_limit_error,
    is_retryable_search_error,
)
from myrm_agent_harness.toolkits.web_search.core.exceptions import (
    ErrorContext,
    SearchAPIError,
)
from myrm_agent_harness.toolkits.web_search.providers.chain import _should_stop_chain


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
