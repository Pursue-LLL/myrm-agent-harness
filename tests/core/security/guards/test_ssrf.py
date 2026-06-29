"""Tests for core outbound URL SSRF protection."""

from __future__ import annotations

import socket
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.core.security.guards.ssrf import (
    SSRFSecurityError,
    async_pin_url,
    is_internal_ip,
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
        assert is_internal_ip("0.0.0.0") is True
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
    async def test_blocks_internal_ip(self):
        with mock_getaddrinfo("192.168.1.100"):
            with pytest.raises(SSRFSecurityError, match="Access to internal network is blocked"):
                await async_pin_url("http://192.168.1.100/admin")

    @pytest.mark.asyncio
    async def test_blocks_internal_ip_records_audit(self):
        with mock_getaddrinfo("192.168.1.100"):
            with patch("myrm_agent_harness.core.security.guards.ssrf.record_decision") as mock_audit:
                with pytest.raises(SSRFSecurityError):
                    await async_pin_url("http://192.168.1.100/admin")

        mock_audit.assert_called_once()
        assert mock_audit.call_args.args[1] == "SSRF_BLOCKED"

    @pytest.mark.asyncio
    async def test_blocks_dns_rebinding(self):
        with mock_getaddrinfo("127.0.0.1"):
            with pytest.raises(SSRFSecurityError, match="Access to internal network is blocked"):
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
            safe_url, headers = await async_pin_url(
                "http://10.0.0.5:9000/data", allowed_internal_hosts=["10.0.0.5"]
            )

            assert safe_url == "http://10.0.0.5:9000/data"
            assert headers == {}


class TestURLAllowlistGuard:
    """Test URL Allowlist Guard (DLP protection)."""

    @pytest.mark.asyncio
    async def test_allowlist_guard_allows_matching_domain(self):
        with mock_getaddrinfo("8.8.8.8"), URLAllowlistGuard.apply(["api.github.com"]):
            safe_url, _headers = await async_pin_url("https://api.github.com/users")
            assert safe_url == "https://8.8.8.8/users"

    @pytest.mark.asyncio
    async def test_allowlist_guard_blocks_unauthorized_domain(self):
        with mock_getaddrinfo("8.8.8.8"), URLAllowlistGuard.apply(["api.github.com"]):
            with pytest.raises(SSRFSecurityError, match="Access to evil.com is blocked"):
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
