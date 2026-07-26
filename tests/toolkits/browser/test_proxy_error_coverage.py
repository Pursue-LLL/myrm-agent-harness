"""Tests for proxy_error.py uncovered branches."""

from __future__ import annotations

from myrm_agent_harness.toolkits.browser.utils.proxy_error import (
    is_blocked_response,
    is_proxy_error,
)


class TestIsProxyError:
    def test_exception_with_proxy_pattern(self) -> None:
        assert is_proxy_error(ConnectionError("net::ERR_PROXY_CONNECTION_FAILED"))

    def test_string_with_proxy_pattern(self) -> None:
        assert is_proxy_error("net::err_tunnel_connection_failed")

    def test_no_match(self) -> None:
        assert not is_proxy_error("some random error")

    def test_none_value(self) -> None:
        assert not is_proxy_error(None)

    def test_page_closed(self) -> None:
        assert is_proxy_error("Page closed unexpectedly")

    def test_browser_closed(self) -> None:
        assert is_proxy_error("browser has been closed")


class TestIsBlockedResponse:
    def test_403_status(self) -> None:
        assert is_blocked_response(403)

    def test_429_status(self) -> None:
        assert is_blocked_response(429)

    def test_200_status(self) -> None:
        assert not is_blocked_response(200)

    def test_cloudflare_challenge(self) -> None:
        assert is_blocked_response(200, "Cloudflare Challenge page")

    def test_datadome(self) -> None:
        assert is_blocked_response(200, "DataDome security check")

    def test_captcha_verify(self) -> None:
        assert is_blocked_response(200, "Please verify the captcha")

    def test_no_body_match(self) -> None:
        assert not is_blocked_response(200, "Normal page content")

    def test_empty_body(self) -> None:
        assert not is_blocked_response(200, "")
