"""Unit tests for RedirectHeaderForwardGuard and Origin security rules."""

from __future__ import annotations

import httpx
import pytest

from myrm_agent_harness.core.security.http.redirect_guard import (
    InsecureRedirectSecurityError,
    Origin,
    create_mcp_redirect_guard_event_hooks,
    extract_origin,
    is_same_origin,
    is_sensitive_header,
    strip_sensitive_headers_on_redirect,
)


class TestOriginExtractionAndComparison:
    """Tests for Origin parsing, default port normalization, and same-origin checks."""

    def test_extract_origin_standard_ports(self) -> None:
        origin_https = extract_origin("https://api.example.com/v1/tools")
        assert origin_https == Origin(scheme="https", host="api.example.com", port=443)
        assert origin_https.is_secure is True

        origin_http = extract_origin("http://insecure.example.com/data")
        assert origin_http == Origin(scheme="http", host="insecure.example.com", port=80)
        assert origin_http.is_secure is False

    def test_extract_origin_explicit_ports(self) -> None:
        origin_custom = extract_origin("https://custom.example.com:8443/mcp")
        assert origin_custom == Origin(scheme="https", host="custom.example.com", port=8443)

    def test_extract_origin_invalid(self) -> None:
        assert extract_origin("not-a-valid-url") is None
        assert extract_origin("") is None

    def test_is_same_origin_same_host_and_scheme(self) -> None:
        u1 = "https://example.com/path1"
        u2 = "https://example.com/path2/subpath"
        assert is_same_origin(u1, u2) is True

    def test_is_same_origin_default_port_equivalence(self) -> None:
        u1 = "https://example.com/v1"
        u2 = "https://example.com:443/v1"
        assert is_same_origin(u1, u2) is True

        u3 = "http://example.com/v1"
        u4 = "http://example.com:80/v1"
        assert is_same_origin(u3, u4) is True

    def test_is_same_origin_cross_domain(self) -> None:
        u1 = "https://example.com/v1"
        u2 = "https://evil.com/v1"
        assert is_same_origin(u1, u2) is False

    def test_is_same_origin_cross_subdomain(self) -> None:
        u1 = "https://api.example.com/v1"
        u2 = "https://auth.example.com/v1"
        assert is_same_origin(u1, u2) is False

    def test_is_same_origin_cross_port(self) -> None:
        u1 = "https://example.com:8443/v1"
        u2 = "https://example.com:443/v1"
        assert is_same_origin(u1, u2) is False

    def test_is_same_origin_cross_scheme(self) -> None:
        u1 = "https://example.com/v1"
        u2 = "http://example.com/v1"
        assert is_same_origin(u1, u2) is False


class TestSensitiveHeaderIdentification:
    """Tests for header sensitivity categorization."""

    @pytest.mark.parametrize(
        "header_name",
        [
            "authorization",
            "Authorization",
            "AUTHORIZATION",
            "cookie",
            "Cookie",
            "set-cookie",
            "Proxy-Authorization",
            "x-csrf-token",
            "X-CSRF-TOKEN",
            "x-xsrf-token",
            "x-auth-token",
            "x-api-key",
            "X-Api-Key",
            "apikey",
            "token",
            "secret",
            "x-client-secret",
            "x_access_token",
            "bearer_token",
            "session_token",
            "private-key",
        ],
    )
    def test_sensitive_headers_recognized(self, header_name: str) -> None:
        assert is_sensitive_header(header_name) is True

    @pytest.mark.parametrize(
        "header_name",
        [
            "content-type",
            "Content-Type",
            "accept",
            "Accept",
            "user-agent",
            "x-custom-request-id",
            "x-tenant-id",
            "cache-control",
        ],
    )
    def test_non_sensitive_headers_passed(self, header_name: str) -> None:
        assert is_sensitive_header(header_name) is False

    def test_custom_sensitive_headers(self) -> None:
        custom = frozenset({"x-internal-pin", "my-app-session"})
        assert is_sensitive_header("x-internal-pin", custom) is True
        assert is_sensitive_header("my-app-session", custom) is True
        assert is_sensitive_header("other-header", custom) is False


class TestHeaderSanitizationOnRedirect:
    """Tests for strip_sensitive_headers_on_redirect function."""

    def test_same_origin_preserves_all_headers(self) -> None:
        headers = {
            "Authorization": "Bearer token123",
            "Cookie": "session=abc",
            "X-Custom-Data": "12345",
        }
        sanitized = strip_sensitive_headers_on_redirect(
            from_url="https://api.corp.com/v1",
            to_url="https://api.corp.com/v2/redirect",
            headers=headers,
        )
        assert sanitized == headers

    def test_cross_origin_strips_sensitive_headers(self) -> None:
        headers = {
            "Authorization": "Bearer token123",
            "Cookie": "session=abc",
            "X-API-KEY": "secret-key-999",
            "Content-Type": "application/json",
            "User-Agent": "Myrm-Agent/1.0",
        }
        sanitized = strip_sensitive_headers_on_redirect(
            from_url="https://api.corp.com/v1",
            to_url="https://third-party.evil.com/collect",
            headers=headers,
        )
        assert "Authorization" not in sanitized
        assert "Cookie" not in sanitized
        assert "X-API-KEY" not in sanitized
        assert sanitized["Content-Type"] == "application/json"
        assert sanitized["User-Agent"] == "Myrm-Agent/1.0"

    def test_https_to_http_downgrade_raises_insecure_error(self) -> None:
        headers = {"Authorization": "Bearer token123"}
        with pytest.raises(InsecureRedirectSecurityError, match="Insecure protocol downgrade"):
            strip_sensitive_headers_on_redirect(
                from_url="https://secure.example.com/v1",
                to_url="http://insecure.example.com/v1",
                headers=headers,
            )

    def test_https_to_http_downgrade_allowed_strips_sensitive(self) -> None:
        headers = {
            "Authorization": "Bearer token123",
            "Content-Type": "application/json",
        }
        sanitized = strip_sensitive_headers_on_redirect(
            from_url="https://secure.example.com/v1",
            to_url="http://insecure.example.com/v1",
            headers=headers,
            allow_insecure_downgrade=True,
        )
        assert "Authorization" not in sanitized
        assert sanitized["Content-Type"] == "application/json"


class TestMcpRedirectGuardEventHooks:
    """Tests for create_mcp_redirect_guard_event_hooks on httpx/httpx2 requests."""

    @pytest.mark.asyncio
    async def test_event_hook_strips_cross_origin_headers(self) -> None:
        hooks = create_mcp_redirect_guard_event_hooks("https://api.mcp-provider.com/sse")
        assert "request" in hooks
        request_hook = hooks["request"][0]

        # Request to same origin
        req_same = httpx.Request(
            "GET",
            "https://api.mcp-provider.com/stream",
            headers={"Authorization": "Bearer tok", "X-Custom": "val"},
        )
        await request_hook(req_same)
        assert req_same.headers["Authorization"] == "Bearer tok"
        assert req_same.headers["X-Custom"] == "val"

        # Request redirected to cross origin
        req_cross = httpx.Request(
            "GET",
            "https://evil-hacker.com/stream",
            headers={"Authorization": "Bearer tok", "X-Custom": "val"},
        )
        await request_hook(req_cross)
        assert "Authorization" not in req_cross.headers
        assert req_cross.headers["X-Custom"] == "val"

    @pytest.mark.asyncio
    async def test_event_hook_blocks_protocol_downgrade(self) -> None:
        hooks = create_mcp_redirect_guard_event_hooks("https://api.mcp-provider.com/sse")
        request_hook = hooks["request"][0]

        req_downgrade = httpx.Request(
            "GET",
            "http://api.mcp-provider.com/stream",
            headers={"Authorization": "Bearer tok"},
        )
        with pytest.raises(InsecureRedirectSecurityError):
            await request_hook(req_downgrade)
