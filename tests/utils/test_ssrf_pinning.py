"""Tests for SSRF validation with DNS pinning.

Covers SSRFResult, validate_url_for_ssrf, async_validate_url_for_ssrf,
create_pinned_transport, and build_host_resolver_rules.
"""

from __future__ import annotations

import ipaddress
import socket
from unittest.mock import patch

import pytest

from myrm_agent_harness.core.security.guards.ssrf import (
    SSRFResult,
    async_validate_url_for_ssrf,
    validate_url_for_ssrf,
)
from myrm_agent_harness.utils.url_utils import (
    build_host_resolver_rules,
    create_dns_pin_map,
    is_blocked_ip,
    validate_scheme_and_hostname,
)

# ---------------------------------------------------------------------------
# SSRFResult
# ---------------------------------------------------------------------------


class TestSSRFResult:
    def test_safe_result_fields(self) -> None:
        r = SSRFResult(safe=True, hostname="example.com", resolved_ips=("1.2.3.4",))
        assert r.safe is True
        assert r.hostname == "example.com"
        assert r.resolved_ips == ("1.2.3.4",)
        assert r.error == ""

    def test_unsafe_result_fields(self) -> None:
        r = SSRFResult(safe=False, error="blocked", hostname="evil.com")
        assert r.safe is False
        assert r.error == "blocked"
        assert r.resolved_ips == ()

    def test_backward_compatible_unpacking(self) -> None:
        r = SSRFResult(safe=True, hostname="ok.com", resolved_ips=("5.6.7.8",))
        ok, err = r
        assert ok is True
        assert err == ""

    def test_backward_compatible_unpacking_unsafe(self) -> None:
        r = SSRFResult(safe=False, error="bad ip")
        ok, err = r
        assert ok is False
        assert err == "bad ip"

    def test_frozen(self) -> None:
        r = SSRFResult(safe=True, hostname="x.com", resolved_ips=("1.1.1.1",))
        with pytest.raises(AttributeError):
            r.safe = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# is_blocked_ip (via check_ip_blocked-style assertions)
# ---------------------------------------------------------------------------


class TestCheckIPBlocked:
    def test_loopback_blocked(self) -> None:
        assert is_blocked_ip("127.0.0.1") is True

    def test_private_10_blocked(self) -> None:
        assert is_blocked_ip("10.0.0.1") is True

    def test_private_172_blocked(self) -> None:
        assert is_blocked_ip("172.16.0.1") is True

    def test_private_192_blocked(self) -> None:
        assert is_blocked_ip("192.168.1.1") is True

    def test_link_local_blocked(self) -> None:
        assert is_blocked_ip("169.254.169.254") is True

    def test_ipv6_loopback_blocked(self) -> None:
        assert is_blocked_ip("::1") is True

    def test_cgnat_blocked(self) -> None:
        assert is_blocked_ip("100.64.0.1") is True

    def test_cgnat_upper_blocked(self) -> None:
        assert is_blocked_ip("100.127.255.254") is True

    def test_fake_ip_allowed(self) -> None:
        assert is_blocked_ip("198.18.0.1") is False

    def test_multicast_blocked(self) -> None:
        assert is_blocked_ip("224.0.0.1") is True

    def test_reserved_blocked(self) -> None:
        assert is_blocked_ip("240.0.0.1") is True

    def test_public_ip_allowed(self) -> None:
        assert is_blocked_ip("8.8.8.8") is False

    def test_public_ipv6_allowed(self) -> None:
        assert is_blocked_ip("2001:4860:4860::8888") is False

    def test_ipv4_mapped_loopback_blocked(self) -> None:
        assert is_blocked_ip("::ffff:127.0.0.1") is True

    def test_ipv4_mapped_private_blocked(self) -> None:
        assert is_blocked_ip("::ffff:10.0.0.1") is True

    def test_ipv4_mapped_cgnat_blocked(self) -> None:
        assert is_blocked_ip("::ffff:100.64.0.1") is True

    def test_ipv4_mapped_fake_ip_allowed(self) -> None:
        assert is_blocked_ip("::ffff:198.18.0.1") is False

    def test_ipv4_mapped_public_allowed(self) -> None:
        assert is_blocked_ip("::ffff:8.8.8.8") is False

    def test_unspecified_blocked(self) -> None:
        assert is_blocked_ip("0.0.0.0") is True

    def test_doc_test_net_blocked(self) -> None:
        assert is_blocked_ip("192.0.2.1") is True


class TestIsBlockedIPEdgeCases:
    """Edge cases for is_blocked_ip with string inputs."""

    def test_empty_string_blocked(self) -> None:
        assert is_blocked_ip("") is True

    def test_invalid_format_blocked(self) -> None:
        assert is_blocked_ip("not-an-ip") is True

    def test_octal_format_blocked(self) -> None:
        assert is_blocked_ip("0177.0.0.1") is True

    def test_broadcast_blocked(self) -> None:
        assert is_blocked_ip("255.255.255.255") is True

    def test_ipv6_compressed_loopback_blocked(self) -> None:
        assert is_blocked_ip("::1") is True

    def test_ipv6_full_loopback_blocked(self) -> None:
        assert is_blocked_ip("0000:0000:0000:0000:0000:0000:0000:0001") is True

    def test_ipv4_mapped_fake_ip_string_allowed(self) -> None:
        assert is_blocked_ip("::ffff:198.18.0.1") is False

    def test_cgnat_boundary_low_blocked(self) -> None:
        assert is_blocked_ip("100.64.0.0") is True

    def test_cgnat_boundary_high_blocked(self) -> None:
        assert is_blocked_ip("100.127.255.255") is True

    def test_just_above_cgnat_allowed(self) -> None:
        assert is_blocked_ip("100.128.0.0") is False

    def test_public_dns_allowed(self) -> None:
        assert is_blocked_ip("1.1.1.1") is False


# ---------------------------------------------------------------------------
# validate_scheme_and_hostname
# ---------------------------------------------------------------------------


class TestValidateSchemeAndHostname:
    def test_valid_https(self) -> None:
        hostname, err = validate_scheme_and_hostname("https://example.com/path")
        assert hostname == "example.com"
        assert err == ""

    def test_blocked_scheme(self) -> None:
        hostname, err = validate_scheme_and_hostname("ftp://example.com")
        assert hostname is None
        assert "scheme" in err.lower()

    def test_blocked_hostname(self) -> None:
        hostname, err = validate_scheme_and_hostname("https://localhost/path")
        assert hostname is None
        assert "localhost" in err.lower()

    def test_cloud_metadata_blocked(self) -> None:
        hostname, _err = validate_scheme_and_hostname("http://169.254.169.254/latest")
        assert hostname is None

    def test_missing_hostname(self) -> None:
        hostname, _err = validate_scheme_and_hostname("http://")
        assert hostname is None


# ---------------------------------------------------------------------------
# validate_url_for_ssrf (sync) — returns SSRFResult with resolved_ips
# ---------------------------------------------------------------------------

_FAKE_ADDRS = [(socket.AF_INET, 0, 0, "", ("93.184.216.34", 0))]


class TestValidateUrlForSSRF:
    def test_public_url_returns_resolved_ips(self) -> None:
        with patch("socket.getaddrinfo", return_value=_FAKE_ADDRS):
            result = validate_url_for_ssrf("https://example.com")
        assert result.safe is True
        assert result.resolved_ips == ("93.184.216.34",)
        assert result.hostname == "example.com"

    def test_blocked_scheme(self) -> None:
        result = validate_url_for_ssrf("ftp://evil.com")
        assert result.safe is False
        assert "scheme" in result.error.lower()

    def test_private_ip_literal(self) -> None:
        result = validate_url_for_ssrf("http://10.0.0.1/secret")
        assert result.safe is False

    def test_dns_resolves_to_private(self) -> None:
        private = [(socket.AF_INET, 0, 0, "", ("127.0.0.1", 0))]
        with patch("socket.getaddrinfo", return_value=private):
            result = validate_url_for_ssrf("https://evil-rebind.com")
        assert result.safe is False
        assert "127.0.0.1" in result.error

    def test_dns_failure(self) -> None:
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("no host")):
            result = validate_url_for_ssrf("https://nonexistent.invalid")
        assert result.safe is False
        assert "DNS" in result.error

    def test_backward_compat_tuple_unpack(self) -> None:
        with patch("socket.getaddrinfo", return_value=_FAKE_ADDRS):
            is_safe, error = validate_url_for_ssrf("https://example.com")
        assert is_safe is True
        assert error == ""

    def test_ip_literal_safe(self) -> None:
        result = validate_url_for_ssrf("http://8.8.8.8/dns")
        assert result.safe is True
        assert result.resolved_ips == ("8.8.8.8",)

    def test_cgnat_ip_literal_blocked(self) -> None:
        result = validate_url_for_ssrf("http://100.64.0.1/admin")
        assert result.safe is False

    def test_fake_ip_literal_allowed(self) -> None:
        result = validate_url_for_ssrf("http://198.18.0.1/proxy")
        assert result.safe is True
        assert result.resolved_ips == ("198.18.0.1",)

    def test_dns_resolves_to_cgnat_blocked(self) -> None:
        cgnat = [(socket.AF_INET, 0, 0, "", ("100.64.1.1", 0))]
        with patch("socket.getaddrinfo", return_value=cgnat):
            result = validate_url_for_ssrf("https://internal.corp")
        assert result.safe is False

    def test_multiple_ips_deduped(self) -> None:
        multi = [
            (socket.AF_INET, 0, 0, "", ("1.2.3.4", 0)),
            (socket.AF_INET, 0, 0, "", ("1.2.3.4", 0)),
            (socket.AF_INET, 0, 0, "", ("5.6.7.8", 0)),
        ]
        with patch("socket.getaddrinfo", return_value=multi):
            result = validate_url_for_ssrf("https://multi.example.com")
        assert result.resolved_ips == ("1.2.3.4", "5.6.7.8")


# ---------------------------------------------------------------------------
# async_validate_url_for_ssrf
# ---------------------------------------------------------------------------


class TestAsyncValidateUrlForSSRF:
    @pytest.mark.asyncio
    async def test_public_url_async(self) -> None:
        with patch(
            "myrm_agent_harness.core.security.guards.ssrf._resolve_and_check_async",
            return_value=SSRFResult(safe=True, hostname="example.com", resolved_ips=("93.184.216.34",)),
        ):
            result = await async_validate_url_for_ssrf("https://example.com")

        assert result.safe is True
        assert result.resolved_ips == ("93.184.216.34",)

    @pytest.mark.asyncio
    async def test_blocked_ip_async(self) -> None:
        result = await async_validate_url_for_ssrf("http://127.0.0.1/secret")
        assert result.safe is False


# ---------------------------------------------------------------------------
# create_pinned_transport
# ---------------------------------------------------------------------------


class TestCreateDnsPinMap:
    def test_builds_pin_map(self) -> None:
        results = [
            SSRFResult(safe=True, hostname="a.com", resolved_ips=("1.2.3.4",)),
            SSRFResult(safe=True, hostname="b.com", resolved_ips=("5.6.7.8", "9.10.11.12")),
        ]
        pin_map, err = create_dns_pin_map(results)
        assert err is None
        assert pin_map == {"a.com": "1.2.3.4", "b.com": "5.6.7.8"}

    def test_returns_error_on_unsafe(self) -> None:
        results = [
            SSRFResult(safe=True, hostname="ok.com", resolved_ips=("1.1.1.1",)),
            SSRFResult(safe=False, error="bad"),
        ]
        pin_map, err = create_dns_pin_map(results)
        assert err == "bad"
        assert pin_map == {}

    def test_empty_results(self) -> None:
        pin_map, err = create_dns_pin_map([])
        assert err is None
        assert pin_map == {}


# ---------------------------------------------------------------------------
# build_host_resolver_rules
# ---------------------------------------------------------------------------


class TestBuildHostResolverRules:
    def test_single_host(self) -> None:
        results = [SSRFResult(safe=True, hostname="x.com", resolved_ips=("1.2.3.4",))]
        assert build_host_resolver_rules(results) == "MAP x.com 1.2.3.4"

    def test_multiple_hosts(self) -> None:
        results = [
            SSRFResult(safe=True, hostname="a.com", resolved_ips=("1.1.1.1",)),
            SSRFResult(safe=True, hostname="b.com", resolved_ips=("2.2.2.2",)),
        ]
        assert build_host_resolver_rules(results) == "MAP a.com 1.1.1.1, MAP b.com 2.2.2.2"

    def test_skips_unsafe(self) -> None:
        results = [
            SSRFResult(safe=True, hostname="ok.com", resolved_ips=("1.1.1.1",)),
            SSRFResult(safe=False, error="bad", hostname="evil.com"),
        ]
        assert build_host_resolver_rules(results) == "MAP ok.com 1.1.1.1"

    def test_empty(self) -> None:
        assert build_host_resolver_rules([]) == ""
