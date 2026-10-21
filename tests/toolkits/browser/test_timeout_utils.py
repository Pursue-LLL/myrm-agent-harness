"""Unit tests for browser timeout detection helpers."""

from patchright.async_api import TimeoutError as PlaywrightTimeoutError

from myrm_agent_harness.toolkits.browser.utils.timeout import is_timeout_error


def test_is_timeout_error_recognizes_builtin() -> None:
    assert is_timeout_error(TimeoutError("navigation timed out"))


def test_is_timeout_error_recognizes_patchright() -> None:
    assert is_timeout_error(PlaywrightTimeoutError("page.goto: Timeout 30000ms exceeded"))


def test_is_timeout_error_rejects_other_errors() -> None:
    assert not is_timeout_error(RuntimeError("unexpected failure"))
    assert not is_timeout_error(ConnectionError("connection refused"))
    assert not is_timeout_error(ValueError("bad url"))
