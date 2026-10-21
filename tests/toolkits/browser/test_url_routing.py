"""Unit tests for url_routing module — private URL detection."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.browser.url_routing import (
    _is_private_ip,
    _resolve_is_private,
    is_private_url,
)


class TestIsPrivateUrl:
    """Test is_private_url() detection logic."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:3000",
            "http://localhost/api",
            "https://localhost:8443/path",
        ],
    )
    def test_localhost_exact(self, url: str) -> None:
        assert is_private_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "http://sub.localhost:4200",
            "http://api.localhost:8080/v1",
            "http://deep.nested.localhost:3000",
        ],
    )
    def test_localhost_suffix(self, url: str) -> None:
        assert is_private_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "http://myapp.local:3000",
            "http://printer.local",
            "http://service.internal:5000",
            "http://router.lan/admin",
            "http://dev.lan/dashboard",
        ],
    )
    def test_private_hostname_suffixes(self, url: str) -> None:
        assert is_private_url(url) is True

    @pytest.mark.parametrize(
        "url,description",
        [
            ("http://127.0.0.1:8080/api", "loopback"),
            ("http://10.0.0.1:9000", "RFC1918 class A"),
            ("http://10.255.255.255:80", "RFC1918 class A upper"),
            ("http://172.16.0.1:8080", "RFC1918 class B lower"),
            ("http://172.31.255.255:80", "RFC1918 class B upper"),
            ("http://192.168.1.1/admin", "RFC1918 class C"),
            ("http://192.168.255.255:80", "RFC1918 class C upper"),
            ("http://169.254.1.1:8080", "link-local"),
            ("http://100.64.0.1:8000", "CGNAT"),
            ("http://100.127.255.254:80", "CGNAT upper"),
        ],
    )
    def test_private_ipv4_literal(self, url: str, description: str) -> None:
        assert is_private_url(url) is True, f"Failed for {description}"

    @pytest.mark.parametrize(
        "url",
        [
            "http://[::1]:8080",
            "http://[fe80::1]:3000",
            "http://[fd00::1]:9090",
        ],
    )
    def test_private_ipv6_literal(self, url: str) -> None:
        assert is_private_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://google.com",
            "https://github.com/repo",
            "https://example.com:8080/api",
            "http://8.8.8.8:53",
            "https://1.1.1.1",
            "http://203.0.114.1:80",
        ],
    )
    def test_public_urls(self, url: str) -> None:
        assert is_private_url(url) is False

    @pytest.mark.parametrize(
        "url,description",
        [
            ("http://198.18.1.32:443", "benchmark range — NOT private"),
            ("http://192.0.2.1:80", "TEST-NET-1 — NOT private"),
            ("http://198.51.100.1:80", "TEST-NET-2 — NOT private"),
            ("http://203.0.113.1:80", "TEST-NET-3 — NOT private"),
        ],
    )
    def test_non_private_reserved_ranges(self, url: str, description: str) -> None:
        """Ranges that ip.is_private considers private but are NOT internal networks."""
        assert is_private_url(url) is False, f"Failed for {description}"

    def test_empty_url(self) -> None:
        assert is_private_url("") is False

    def test_invalid_url(self) -> None:
        assert is_private_url("not-a-url") is False

    def test_no_hostname(self) -> None:
        assert is_private_url("file:///etc/passwd") is False

    def test_dns_resolution_private(self) -> None:
        """When DNS resolves to a private IP, should return True."""
        with patch("myrm_agent_harness.toolkits.browser.url_routing.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (2, 1, 6, "", ("192.168.1.100", 0)),
            ]
            assert is_private_url("http://my-internal-service.corp:8080") is True

    def test_dns_resolution_public(self) -> None:
        """When DNS resolves to a public IP, should return False."""
        with patch("myrm_agent_harness.toolkits.browser.url_routing.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (2, 1, 6, "", ("142.250.80.46", 0)),
            ]
            assert is_private_url("http://some-domain.com:8080") is False

    def test_dns_failure_returns_false(self) -> None:
        """DNS failure should return False (not private)."""
        import socket

        with patch(
            "myrm_agent_harness.toolkits.browser.url_routing.socket.getaddrinfo",
            side_effect=socket.gaierror("Name resolution failed"),
        ):
            assert is_private_url("http://nonexistent.xyz:8080") is False

    def test_exception_returns_false(self) -> None:
        """Unexpected exceptions should return False (fail-safe)."""
        with patch(
            "myrm_agent_harness.toolkits.browser.url_routing.urlparse",
            side_effect=RuntimeError("unexpected"),
        ):
            assert is_private_url("http://any.url") is False

    def test_case_insensitive(self) -> None:
        assert is_private_url("http://LOCALHOST:3000") is True
        assert is_private_url("http://Service.Internal:5000") is True

    def test_trailing_dot_fqdn(self) -> None:
        assert is_private_url("http://localhost.") is True

    def test_url_with_auth(self) -> None:
        assert is_private_url("http://user:pass@localhost:3000/api") is True
        assert is_private_url("http://user:pass@google.com/api") is False

    def test_url_with_path_query_fragment(self) -> None:
        assert is_private_url("http://192.168.1.1/admin?page=1#section") is True

    @pytest.mark.parametrize(
        "url",
        [
            "http://[::ffff:127.0.0.1]:8080",
            "http://[::ffff:192.168.1.1]:8080",
            "http://[::ffff:10.0.0.1]:9090",
        ],
    )
    def test_ipv4_mapped_ipv6(self, url: str) -> None:
        """IPv4-mapped IPv6 addresses should be detected as private."""
        assert is_private_url(url) is True

    def test_non_http_scheme_still_detects(self) -> None:
        assert is_private_url("ftp://localhost") is True
        assert is_private_url("ws://192.168.1.1:8080") is True

    def test_invalid_ip_like_hostname(self) -> None:
        assert is_private_url("http://999.999.999.999") is False


class TestIsPrivateIp:
    """Test _is_private_ip() helper directly."""

    def test_ipv4_rfc1918(self) -> None:
        import ipaddress

        assert _is_private_ip(ipaddress.ip_address("10.0.0.1")) is True
        assert _is_private_ip(ipaddress.ip_address("172.16.0.1")) is True
        assert _is_private_ip(ipaddress.ip_address("192.168.0.1")) is True

    def test_ipv4_loopback(self) -> None:
        import ipaddress

        assert _is_private_ip(ipaddress.ip_address("127.0.0.1")) is True
        assert _is_private_ip(ipaddress.ip_address("127.255.255.255")) is True

    def test_ipv4_public(self) -> None:
        import ipaddress

        assert _is_private_ip(ipaddress.ip_address("8.8.8.8")) is False
        assert _is_private_ip(ipaddress.ip_address("198.18.1.1")) is False

    def test_ipv6_loopback(self) -> None:
        import ipaddress

        assert _is_private_ip(ipaddress.ip_address("::1")) is True

    def test_ipv6_ula(self) -> None:
        import ipaddress

        assert _is_private_ip(ipaddress.ip_address("fd12:3456::1")) is True

    def test_ipv6_public(self) -> None:
        import ipaddress

        assert _is_private_ip(ipaddress.ip_address("2001:4860:4860::8888")) is False

    def test_ipv4_mapped_private(self) -> None:
        import ipaddress

        assert _is_private_ip(ipaddress.ip_address("::ffff:127.0.0.1")) is True
        assert _is_private_ip(ipaddress.ip_address("::ffff:192.168.1.1")) is True
        assert _is_private_ip(ipaddress.ip_address("::ffff:10.0.0.1")) is True

    def test_ipv4_mapped_public(self) -> None:
        import ipaddress

        assert _is_private_ip(ipaddress.ip_address("::ffff:8.8.8.8")) is False
        assert _is_private_ip(ipaddress.ip_address("::ffff:198.18.1.1")) is False


class TestResolveIsPrivate:
    """Test _resolve_is_private() DNS resolution path."""

    def test_resolves_to_private(self) -> None:
        with patch("myrm_agent_harness.toolkits.browser.url_routing.socket.getaddrinfo") as mock:
            mock.return_value = [(2, 1, 6, "", ("10.0.0.5", 0))]
            assert _resolve_is_private("internal.corp") is True

    def test_resolves_to_public(self) -> None:
        with patch("myrm_agent_harness.toolkits.browser.url_routing.socket.getaddrinfo") as mock:
            mock.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
            assert _resolve_is_private("example.com") is False

    def test_dns_failure(self) -> None:
        import socket

        with patch(
            "myrm_agent_harness.toolkits.browser.url_routing.socket.getaddrinfo",
            side_effect=socket.gaierror,
        ):
            assert _resolve_is_private("bad.host") is False

    def test_empty_result(self) -> None:
        with patch("myrm_agent_harness.toolkits.browser.url_routing.socket.getaddrinfo") as mock:
            mock.return_value = []
            assert _resolve_is_private("empty.result") is False

    def test_mixed_ips_one_private(self) -> None:
        """If any resolved IP is private, return True."""
        with patch("myrm_agent_harness.toolkits.browser.url_routing.socket.getaddrinfo") as mock:
            mock.return_value = [
                (2, 1, 6, "", ("8.8.8.8", 0)),
                (2, 1, 6, "", ("192.168.1.1", 0)),
            ]
            assert _resolve_is_private("mixed.host") is True
