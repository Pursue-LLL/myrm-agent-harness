"""Tests for core outbound URL SSRF protection."""

from __future__ import annotations

import socket
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.core.security.guards.ssrf import (
    SSRFResult,
    SSRFSecurityError,
    async_pin_url,
    async_validate_url_for_ssrf,
    clear_dynamic_blocked_hostnames,
    is_internal_ip,
    register_blocked_hostnames,
    unregister_blocked_hostnames,
    validate_url_for_ssrf,
)
from myrm_agent_harness.core.security.guards.url_allowlist import URLAllowlistGuard


def mock_getaddrinfo(ip: str):
    """Create a mock for asyncio.get_running_loop().getaddrinfo."""
    mock_loop = AsyncMock()
    mock_loop.getaddrinfo.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]
    return patch("asyncio.get_running_loop", return_value=mock_loop)


class TestSSRFShield:
    """Test SSRF protection logic."""

    def test_is_internal_ip(self):
        assert is_internal_ip("127.0.0.1") is True
        assert is_internal_ip("192.168.1.1") is True
        assert is_internal_ip("10.0.0.1") is True
        assert is_internal_ip("172.16.0.1") is True
        assert is_internal_ip("169.254.169.254") is True
        assert (
            is_internal_ip("0.0.0.0") is True  # noqa: S104 — string assertion, not a bind
        )
        assert is_internal_ip("::1") is True

        assert is_internal_ip("8.8.8.8") is False
        assert is_internal_ip("1.1.1.1") is False
        assert is_internal_ip("invalid-ip") is True

    def test_cgnat_blocked(self):
        assert is_internal_ip("100.64.0.1") is True
        assert is_internal_ip("100.127.255.254") is True

    def test_fake_ip_allowed(self):
        assert is_internal_ip("198.18.0.1") is False
        assert is_internal_ip("198.19.255.254") is False

    @pytest.mark.asyncio
    async def test_validate_external_url(self):
        with mock_getaddrinfo("8.8.8.8") as mock_loop_patch:
            safe_url, headers = await async_pin_url("https://google.com/search?q=test")

            assert safe_url == "https://8.8.8.8/search?q=test"
            assert headers == {"Host": "google.com"}
            mock_loop = mock_loop_patch.return_value
            mock_loop.getaddrinfo.assert_called_once_with("google.com", None, proto=socket.IPPROTO_TCP)

    @pytest.mark.asyncio
    async def test_validate_external_url_with_port(self):
        with mock_getaddrinfo("8.8.8.8"):
            safe_url, headers = await async_pin_url("http://example.com:8080/api")

            assert safe_url == "http://8.8.8.8:8080/api"
            assert headers == {"Host": "example.com"}

    @pytest.mark.asyncio
    async def test_validate_external_url_ipv6_with_and_without_port(self):
        # Public IPv6 without port: RFC 3986 square bracket wrapping
        with mock_getaddrinfo("2001:4860:4860::8888"):
            safe_url, headers = await async_pin_url("https://google.com/search?q=test")
            assert safe_url == "https://[2001:4860:4860::8888]/search?q=test"
            assert headers == {"Host": "google.com"}

        # Public IPv6 with port: RFC 3986 bracketed host and port separator
        with mock_getaddrinfo("2001:4860:4860::8888"):
            safe_url, headers = await async_pin_url("https://google.com:8443/api")
            assert safe_url == "https://[2001:4860:4860::8888]:8443/api"
            assert headers == {"Host": "google.com"}

    @pytest.mark.asyncio
    async def test_blocks_internal_ip(self):
        with (
            mock_getaddrinfo("192.168.1.100"),
            pytest.raises(SSRFSecurityError, match="Access to internal network is blocked"),
        ):
            await async_pin_url("http://192.168.1.100/admin")

    @pytest.mark.asyncio
    async def test_blocks_internal_ip_records_audit(self):
        with (
            mock_getaddrinfo("192.168.1.100"),
            patch("myrm_agent_harness.core.security.guards.ssrf.record_decision") as mock_audit,
            pytest.raises(SSRFSecurityError),
        ):
            await async_pin_url("http://192.168.1.100/admin")

        mock_audit.assert_called_once()
        assert mock_audit.call_args.args[1] == "SSRF_BLOCKED"

    @pytest.mark.asyncio
    async def test_blocks_dns_rebinding(self):
        with (
            mock_getaddrinfo("127.0.0.1"),
            pytest.raises(SSRFSecurityError, match="Access to internal network is blocked"),
        ):
            await async_pin_url("http://evil-domain.com/flushall")

    @pytest.mark.asyncio
    async def test_allows_whitelisted_hosts(self):
        with mock_getaddrinfo("10.0.0.5") as mock_loop_patch:
            safe_url, headers = await async_pin_url(
                "http://my-internal-nas.example/api",
                allowed_internal_hosts=["my-internal-nas.example"],
            )

            assert safe_url == "http://my-internal-nas.example/api"
            assert headers == {}
            mock_loop_patch.return_value.getaddrinfo.assert_not_called()

    @pytest.mark.asyncio
    async def test_allows_whitelisted_ips(self):
        with mock_getaddrinfo("10.0.0.5"):
            safe_url, headers = await async_pin_url("http://10.0.0.5:9000/data", allowed_internal_hosts=["10.0.0.5"])

            assert safe_url == "http://10.0.0.5:9000/data"
            assert headers == {}


class TestCheckUrlAndResolve:
    """Sync fast-check paths of check_url / resolve_and_check."""

    def test_check_url_invalid_scheme_returns_error(self):
        from myrm_agent_harness.core.security.guards.ssrf import check_url

        verdict = check_url("ftp://x.com/file")
        assert verdict.allowed is False
        assert "scheme" in verdict.reason

    def test_check_url_allows_internal_hostname_in_allowlist(self):
        from myrm_agent_harness.core.security.guards.ssrf import check_url

        verdict = check_url(
            "http://my-internal-nas.example:9000/data",
            allowed_internal_hosts=frozenset({"my-internal-nas.example"}),
        )
        assert verdict.allowed is True

    def test_check_url_blocks_internal_ip_literal(self):
        from myrm_agent_harness.core.security.guards.ssrf import check_url

        verdict = check_url("http://192.168.1.5/admin")
        assert verdict.allowed is False
        assert "private/internal" in verdict.reason

    def test_check_url_allows_public_ip_literal(self):
        from myrm_agent_harness.core.security.guards.ssrf import check_url

        verdict = check_url("https://8.8.8.8/ping")
        assert verdict.allowed is True

    def test_check_url_blocks_internal_hostname_literal(self):
        from myrm_agent_harness.core.security.guards.ssrf import check_url

        verdict = check_url("http://10.0.0.9")
        assert verdict.allowed is False

    def test_resolve_allows_allowlisted_host(self):
        from myrm_agent_harness.core.security.guards.ssrf import resolve_and_check

        verdict = resolve_and_check("nas.internal", allowed_internal_hosts=frozenset({"nas.internal"}))
        assert verdict.allowed is True

    @patch(
        "myrm_agent_harness.core.security.guards.ssrf.socket.getaddrinfo",
        side_effect=socket.gaierror("nxdomain"),
    )
    def test_resolve_dns_failure(self, _mock):
        from myrm_agent_harness.core.security.guards.ssrf import resolve_and_check

        verdict = resolve_and_check("no-such-host.example")
        assert verdict.allowed is False
        assert "resolution failed" in verdict.reason

    @patch("myrm_agent_harness.core.security.guards.ssrf.socket.getaddrinfo")
    def test_resolve_blocks_internal_resolved_ip(self, mock_gai):
        from myrm_agent_harness.core.security.guards.ssrf import resolve_and_check

        mock_gai.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.16.3.9", 0))]
        verdict = resolve_and_check("attacker.example")
        assert verdict.allowed is False
        assert "resolves to private/internal IP" in verdict.reason

    @patch("myrm_agent_harness.core.security.guards.ssrf.socket.getaddrinfo")
    def test_resolve_allows_public_resolved_ip(self, mock_gai):
        from myrm_agent_harness.core.security.guards.ssrf import resolve_and_check

        mock_gai.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 0)),
        ]
        verdict = resolve_and_check("public.example")
        assert verdict.allowed is True

    def test_check_url_allows_public_domain(self):
        from myrm_agent_harness.core.security.guards.ssrf import check_url

        verdict = check_url("https://example.com/docs")
        assert verdict.allowed is True

    @pytest.mark.asyncio
    async def test_async_validate_invalid_scheme(self):
        result = await async_validate_url_for_ssrf("ftp://x.com/file")
        assert result.safe is False
        assert "scheme" in result.error

    @pytest.mark.asyncio
    async def test_async_validate_guard_blocked(self):

        with URLAllowlistGuard.apply(["api.github.com"]):
            result = await async_validate_url_for_ssrf("https://evil.com/log")
            assert result.safe is False
            assert "evil.com" in result.error


class TestURLAllowlistGuard:
    """Test URL Allowlist Guard (DLP protection)."""

    @pytest.mark.asyncio
    async def test_allowlist_guard_allows_matching_domain(self):
        with mock_getaddrinfo("8.8.8.8"), URLAllowlistGuard.apply(["api.github.com"]):
            safe_url, _headers = await async_pin_url("https://api.github.com/users")
            assert safe_url == "https://8.8.8.8/users"

    @pytest.mark.asyncio
    async def test_allowlist_guard_blocks_unauthorized_domain(self):
        with (
            mock_getaddrinfo("8.8.8.8"),
            URLAllowlistGuard.apply(["api.github.com"]),
            pytest.raises(SSRFSecurityError, match=r"Access to evil\.com is blocked"),
        ):
            await async_pin_url("https://evil.com/log")

    def test_check_url_blocks_dlp_violation(self):
        with URLAllowlistGuard.apply(["api.github.com"]):
            from myrm_agent_harness.core.security.guards.ssrf import check_url

            verdict = check_url("https://evil.com/log")
            assert verdict.allowed is False
            assert "evil.com" in verdict.reason

    @pytest.mark.asyncio
    async def test_allowlist_guard_allows_subdomains(self):
        with mock_getaddrinfo("8.8.8.8"), URLAllowlistGuard.apply(["github.com"]):
            safe_url, _headers = await async_pin_url("https://api.github.com/users")
            assert safe_url == "https://8.8.8.8/users"

    @pytest.mark.asyncio
    async def test_allowlist_guard_allows_all_when_none(self):
        with mock_getaddrinfo("8.8.8.8"), URLAllowlistGuard.apply(None):
            safe_url, _headers = await async_pin_url("https://random.com/users")
            assert safe_url == "https://8.8.8.8/users"

    @pytest.mark.asyncio
    async def test_allowlist_guard_supports_leading_dot_and_case_insensitive(self):
        with mock_getaddrinfo("8.8.8.8"), URLAllowlistGuard.apply([".github.com", "  EXAMPLE.ORG  "]):
            # Leading dot allowlist matches subdomain
            safe_url1, _ = await async_pin_url("https://API.GITHUB.COM/users")
            assert safe_url1 == "https://8.8.8.8/users"

            # Leading dot allowlist matches apex domain
            safe_url2, _ = await async_pin_url("https://github.com/users")
            assert safe_url2 == "https://8.8.8.8/users"

            # Stripped whitespace and case-insensitive
            safe_url3, _ = await async_pin_url("https://sub.example.org/data")
            assert safe_url3 == "https://8.8.8.8/data"


class TestValidateUrlForSSRF:
    """validate_url_for_ssrf / async_validate_url_for_ssrf — full sync/async validation."""

    def test_validate_public_ip_literal_safe(self) -> None:
        result = validate_url_for_ssrf("https://8.8.8.8/x")

        assert result.safe is True
        assert result.resolved_ips == ("8.8.8.8",)

    def test_validate_blocked_ip_literal(self) -> None:
        result = validate_url_for_ssrf("http://192.168.1.1/x")

        assert result.safe is False
        assert "Blocked IP" in result.error

    def test_validate_invalid_scheme(self) -> None:
        result = validate_url_for_ssrf("not-a-url")

        assert result.safe is False
        assert "Blocked URL scheme" in result.error

    def test_validate_dns_resolved_public(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "socket.getaddrinfo",
            lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))],
        )

        result = validate_url_for_ssrf("http://good.example/x")

        assert result.safe is True
        assert result.resolved_ips == ("8.8.8.8",)

    def test_validate_dns_resolved_blocked(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "socket.getaddrinfo",
            lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))],
        )

        result = validate_url_for_ssrf("http://evil.example/x")

        assert result.safe is False
        assert "Blocked resolved IP" in result.error

    def test_validate_dns_failure(self, monkeypatch) -> None:
        def raise_gaierror(*_a, **_k):
            raise socket.gaierror("no such host")

        monkeypatch.setattr("socket.getaddrinfo", raise_gaierror)

        result = validate_url_for_ssrf("http://badhost.example/x")

        assert result.safe is False
        assert "DNS resolution failed" in result.error

    def test_validate_allowlist_blocks_unauthorized(self) -> None:
        with URLAllowlistGuard.apply(["api.github.com"]):
            result = validate_url_for_ssrf("https://evil.com/log")

            assert result.safe is False
            assert "evil.com" in result.error

    @pytest.mark.asyncio
    async def test_async_validate_public_ip_literal_safe(self) -> None:
        result = await async_validate_url_for_ssrf("https://8.8.8.8/x")

        assert result.safe is True
        assert result.resolved_ips == ("8.8.8.8",)

    @pytest.mark.asyncio
    async def test_async_validate_blocked_ip_literal(self) -> None:
        result = await async_validate_url_for_ssrf("http://10.0.0.1/x")

        assert result.safe is False
        assert "Blocked IP" in result.error

    @pytest.mark.asyncio
    async def test_async_validate_dns_public(self) -> None:
        with mock_getaddrinfo("8.8.8.8"):
            result = await async_validate_url_for_ssrf("http://good.example/x")

            assert result.safe is True
            assert result.resolved_ips == ("8.8.8.8",)

    @pytest.mark.asyncio
    async def test_async_validate_dns_blocked(self) -> None:
        with mock_getaddrinfo("192.168.1.10"):
            result = await async_validate_url_for_ssrf("http://evil.example/x")

            assert result.safe is False
            assert "Blocked resolved IP" in result.error

    @pytest.mark.asyncio
    async def test_async_validate_dns_failure(self) -> None:
        mock_loop = AsyncMock()
        mock_loop.getaddrinfo.side_effect = socket.gaierror("no such host")

        with patch("asyncio.get_running_loop", return_value=mock_loop):
            result = await async_validate_url_for_ssrf("http://badhost.example/x")

            assert result.safe is False
            assert "DNS resolution failed" in result.error

    @pytest.mark.asyncio
    async def test_async_pin_url_invalid_scheme(self) -> None:
        with pytest.raises(SSRFSecurityError, match="Blocked URL scheme"):
            await async_pin_url("not-a-url")

    @pytest.mark.asyncio
    async def test_async_pin_url_empty_resolved_ips(self) -> None:
        async def fake_resolve(hostname: str) -> SSRFResult:
            return SSRFResult(safe=True, hostname=hostname, resolved_ips=())

        with (
            patch(
                "myrm_agent_harness.core.security.guards.ssrf._resolve_and_check_async",
                fake_resolve,
            ),
            pytest.raises(SSRFSecurityError, match="DNS resolution failed"),
        ):
            await async_pin_url("http://nohost.example/x")

    def test_dynamic_blocked_hostnames_registration(self) -> None:
        clear_dynamic_blocked_hostnames()
        try:
            url = "http://cp.internal.enterprise.org/api/dispatch"
            with mock_getaddrinfo("8.8.8.8"):
                res = validate_url_for_ssrf(url)
                assert res.safe is True

            register_blocked_hostnames("cp.internal.enterprise.org")
            res_blocked = validate_url_for_ssrf(url)
            assert res_blocked.safe is False
            assert "Blocked hostname: cp.internal.enterprise.org" in res_blocked.error

            unregister_blocked_hostnames("cp.internal.enterprise.org")
            with mock_getaddrinfo("8.8.8.8"):
                res_restored = validate_url_for_ssrf(url)
                assert res_restored.safe is True
        finally:
            clear_dynamic_blocked_hostnames()

