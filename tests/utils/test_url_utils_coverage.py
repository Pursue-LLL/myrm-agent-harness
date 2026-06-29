"""Tests for url_utils - covering URL normalization, extraction, validation, and SSRF protection."""

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
    extract_domain,
    is_blocked_ip,
    is_file_url,
    is_image_url,
    is_valid_image_url,
    normalize_url,
    validate_scheme_and_hostname,
)


class TestNormalizeUrl:
    def test_basic_normalization(self):
        dedup, full = normalize_url("https://Example.COM/Path/")
        assert dedup == "https://example.com/path"
        assert full == "https://example.com/path"

    def test_removes_www(self):
        dedup, _ = normalize_url("https://www.example.com/page")
        assert "www." not in dedup

    def test_preserves_fragment_in_full(self):
        dedup, full = normalize_url("https://example.com/page#section")
        assert "#" not in dedup
        assert "#section" in full

    def test_decodes_percent_encoding(self):
        dedup, _ = normalize_url("https://example.com/%E4%B8%AD%E6%96%87")
        assert "中文" in dedup

    def test_preserves_query(self):
        dedup, _ = normalize_url("https://example.com/page?key=value")
        assert "key=value" in dedup

    def test_invalid_url_returns_original(self):
        dedup, full = normalize_url("")
        assert dedup == ""
        assert full == ""

    def test_root_path_not_stripped(self):
        dedup, _ = normalize_url("https://example.com/")
        assert dedup == "https://example.com/"


class TestExtractDomain:
    def test_basic(self):
        assert extract_domain("https://example.com/page") == "example.com"

    def test_removes_www(self):
        assert extract_domain("https://www.example.com") == "example.com"

    def test_invalid_url(self):
        assert extract_domain("") == ""


class TestIsValidImageUrl:
    def test_https_valid(self):
        assert is_valid_image_url("https://cdn.example.com/img.png") is True

    def test_http_invalid(self):
        assert is_valid_image_url("http://cdn.example.com/img.png") is False

    def test_localhost_invalid(self):
        assert is_valid_image_url("https://localhost/img.png") is False

    def test_private_ip_invalid(self):
        assert is_valid_image_url("https://192.168.1.1/img.png") is False
        assert is_valid_image_url("https://10.0.0.1/img.png") is False
        assert is_valid_image_url("https://172.16.0.1/img.png") is False


class TestIsImageUrl:
    def test_jpg(self):
        assert is_image_url("https://example.com/photo.jpg") is True

    def test_png_with_query(self):
        assert is_image_url("https://example.com/photo.png?w=100") is True

    def test_not_image(self):
        assert is_image_url("https://example.com/page.html") is False

    def test_svg(self):
        assert is_image_url("https://example.com/icon.svg") is True


class TestIsFileUrl:
    def test_file_with_extension(self):
        assert is_file_url("https://example.com/doc.pdf") is True

    def test_no_extension(self):
        assert is_file_url("https://example.com/page") is False


class TestSSRFResult:
    def test_safe_result_fields(self):
        result = SSRFResult(safe=True, hostname="example.com")
        assert result.safe is True
        assert result.error == ""
        assert result.hostname == "example.com"

    def test_unsafe_result(self):
        result = SSRFResult(safe=False, error="blocked")
        assert result.safe is False
        assert result.error == "blocked"


class TestCheckIpBlocked:
    def test_loopback_blocked(self):
        assert is_blocked_ip("127.0.0.1") is True

    def test_private_blocked(self):
        assert is_blocked_ip("192.168.1.1") is True
        assert is_blocked_ip("10.0.0.1") is True

    def test_public_allowed(self):
        assert is_blocked_ip("8.8.8.8") is False

    def test_link_local_blocked(self):
        assert is_blocked_ip("169.254.169.254") is True


class TestValidateSchemeAndHostname:
    def test_valid_https(self):
        hostname, error = validate_scheme_and_hostname("https://example.com/page")
        assert hostname == "example.com"
        assert error == ""

    def test_blocked_scheme(self):
        hostname, error = validate_scheme_and_hostname("ftp://example.com")
        assert hostname is None
        assert "scheme" in error.lower()

    def test_missing_hostname(self):
        hostname, error = validate_scheme_and_hostname("https://")
        assert hostname is None
        assert "hostname" in error.lower()

    def test_blocked_hostname(self):
        hostname, error = validate_scheme_and_hostname("https://localhost/path")
        assert hostname is None
        assert "blocked" in error.lower()

    def test_cloud_metadata_blocked(self):
        hostname, error = validate_scheme_and_hostname("http://169.254.169.254/latest/meta-data/")
        assert hostname is None
        assert "blocked" in error.lower()

    def test_parser_confusing_tab_blocked(self):
        hostname, error = validate_scheme_and_hostname("http://evil.com\t@169.254.169.254/")
        assert hostname is None
        assert "parser-confusing" in error.lower()

    def test_parser_confusing_newline_blocked(self):
        hostname, error = validate_scheme_and_hostname("http://evil.com\n@169.254.169.254/")
        assert hostname is None
        assert "parser-confusing" in error.lower()

    def test_parser_confusing_backslash_blocked(self):
        hostname, error = validate_scheme_and_hostname("http://evil.com\\@169.254.169.254/")
        assert hostname is None
        assert "parser-confusing" in error.lower()

    def test_parser_confusing_carriage_return_blocked(self):
        hostname, error = validate_scheme_and_hostname("http://evil.com\r@169.254.169.254/")
        assert hostname is None
        assert "parser-confusing" in error.lower()

    def test_trailing_dot_normalized(self):
        hostname, error = validate_scheme_and_hostname("https://example.com./page")
        assert hostname == "example.com"
        assert error == ""

    def test_trailing_dot_localhost_blocked(self):
        hostname, error = validate_scheme_and_hostname("https://localhost./admin")
        assert hostname is None
        assert "blocked" in error.lower()

    def test_local_suffix_blocked(self):
        hostname, error = validate_scheme_and_hostname("http://printer.local/")
        assert hostname is None
        assert "suffix" in error.lower()

    def test_cluster_local_suffix_blocked(self):
        hostname, error = validate_scheme_and_hostname("http://api.cluster.local/")
        assert hostname is None
        assert "suffix" in error.lower()

    def test_svc_suffix_blocked(self):
        hostname, error = validate_scheme_and_hostname("http://my-svc.svc/")
        assert hostname is None
        assert "suffix" in error.lower()

    def test_normal_url_not_affected(self):
        hostname, error = validate_scheme_and_hostname("https://example.com/page")
        assert hostname == "example.com"
        assert error == ""


class TestValidateUrlForSsrf:
    def test_safe_public_url(self):
        result = validate_url_for_ssrf("https://example.com")
        assert result.safe is True
        assert len(result.resolved_ips) > 0

    def test_blocked_localhost(self):
        result = validate_url_for_ssrf("https://localhost")
        assert result.safe is False

    def test_blocked_scheme(self):
        result = validate_url_for_ssrf("ftp://example.com")
        assert result.safe is False

    def test_ip_literal_blocked(self):
        result = validate_url_for_ssrf("https://127.0.0.1/path")
        assert result.safe is False

    def test_ip_literal_public(self):
        result = validate_url_for_ssrf("https://8.8.8.8")
        assert result.safe is True
        assert result.resolved_ips == ("8.8.8.8",)

    def test_dns_failure(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("DNS failed")):
            result = validate_url_for_ssrf("https://nonexistent.invalid")
            assert result.safe is False
            assert "DNS" in result.error

    def test_dns_resolves_to_private(self):
        mock_result = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0))]
        with patch("socket.getaddrinfo", return_value=mock_result):
            result = validate_url_for_ssrf("https://evil.example.com")
            assert result.safe is False
            assert "Blocked resolved IP" in result.error


class TestAsyncValidateUrlForSsrf:
    @pytest.mark.asyncio
    async def test_safe_public_url(self):
        result = await async_validate_url_for_ssrf("https://example.com")
        assert result.safe is True

    @pytest.mark.asyncio
    async def test_blocked_scheme(self):
        result = await async_validate_url_for_ssrf("ftp://example.com")
        assert result.safe is False

    @pytest.mark.asyncio
    async def test_ip_literal_blocked(self):
        result = await async_validate_url_for_ssrf("https://127.0.0.1")
        assert result.safe is False

    @pytest.mark.asyncio
    async def test_ip_literal_public(self):
        result = await async_validate_url_for_ssrf("https://8.8.8.8")
        assert result.safe is True

    @pytest.mark.asyncio
    async def test_dns_failure(self):
        async def mock_getaddrinfo(*args, **kwargs):
            raise socket.gaierror("DNS failed")

        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.getaddrinfo = mock_getaddrinfo
            result = await async_validate_url_for_ssrf("https://nonexistent.invalid")
            assert result.safe is False

    @pytest.mark.asyncio
    async def test_dns_resolves_to_private(self):
        mock_result = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 0))]

        async def mock_getaddrinfo(*args, **kwargs):
            return mock_result

        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value.getaddrinfo = mock_getaddrinfo
            result = await async_validate_url_for_ssrf("https://evil.example.com")
            assert result.safe is False


class TestDnsPinningHelpers:
    def test_create_dns_pin_map_success(self):
        results = [
            SSRFResult(safe=True, hostname="a.com", resolved_ips=("1.2.3.4",)),
            SSRFResult(safe=True, hostname="b.com", resolved_ips=("5.6.7.8",)),
        ]
        pin_map, error = create_dns_pin_map(results)
        assert error is None
        assert pin_map == {"a.com": "1.2.3.4", "b.com": "5.6.7.8"}

    def test_create_dns_pin_map_with_unsafe(self):
        results = [
            SSRFResult(safe=True, hostname="a.com", resolved_ips=("1.2.3.4",)),
            SSRFResult(safe=False, error="blocked", hostname="evil.com"),
        ]
        pin_map, error = create_dns_pin_map(results)
        assert pin_map == {}
        assert error == "blocked"

    def test_build_host_resolver_rules(self):
        results = [
            SSRFResult(safe=True, hostname="a.com", resolved_ips=("1.2.3.4",)),
            SSRFResult(safe=True, hostname="b.com", resolved_ips=("5.6.7.8",)),
        ]
        rules = build_host_resolver_rules(results)
        assert "MAP a.com 1.2.3.4" in rules
        assert "MAP b.com 5.6.7.8" in rules

    def test_build_host_resolver_rules_skips_unsafe(self):
        results = [
            SSRFResult(safe=False, error="blocked", hostname="evil.com"),
        ]
        rules = build_host_resolver_rules(results)
        assert rules == ""

    def test_build_host_resolver_rules_empty(self):
        assert build_host_resolver_rules([]) == ""
