"""Tests for _extract_retry_after_ms in stream_executor."""

import pytest

from myrm_agent_harness.agent.streaming.stream_recovery import _extract_retry_after_ms


class _FakeExcWithHeadersError(Exception):
    def __init__(self, msg: str, headers: dict[str, str] | None = None):
        super().__init__(msg)
        self.headers = headers


def test_extract_from_retry_after_header():
    exc = _FakeExcWithHeadersError("rate limited", headers={"Retry-After": "15"})
    assert _extract_retry_after_ms(exc) == 15_000


def test_extract_from_retry_after_header_float():
    exc = _FakeExcWithHeadersError("rate limited", headers={"retry-after": "30.5"})
    assert _extract_retry_after_ms(exc) == 30_500


def test_extract_from_error_message():
    exc = Exception("Please retry after 45 seconds")
    assert _extract_retry_after_ms(exc) == 45_000


def test_extract_from_error_message_case_insensitive():
    exc = Exception("Retry After 120 Seconds delay")
    assert _extract_retry_after_ms(exc) == 120_000


def test_returns_none_for_no_info():
    exc = Exception("Unknown error occurred")
    assert _extract_retry_after_ms(exc) is None


def test_returns_none_for_empty_headers():
    exc = _FakeExcWithHeadersError("rate limited", headers={})
    assert _extract_retry_after_ms(exc) is None


def test_header_takes_priority_over_message():
    exc = _FakeExcWithHeadersError("Please retry after 999 seconds", headers={"Retry-After": "10"})
    assert _extract_retry_after_ms(exc) == 10_000


def test_response_headers_attribute():
    exc = Exception("rate limited")
    exc.response_headers = {"Retry-After": "20"}  # type: ignore[attr-defined]
    assert _extract_retry_after_ms(exc) == 20_000


@pytest.mark.parametrize(
    "msg",
    [
        "billing error",
        "authentication failed",
        "context length exceeded",
    ],
)
def test_non_transient_errors_return_none(msg: str):
    exc = Exception(msg)
    assert _extract_retry_after_ms(exc) is None
