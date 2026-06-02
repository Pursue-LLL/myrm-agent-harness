"""Tests for security.guards.ssrf_guard — SSRF protection."""

from __future__ import annotations

from unittest.mock import patch

from myrm_agent_harness.agent.security.guards.ssrf_guard import check_url, resolve_and_check
from myrm_agent_harness.utils.url_utils import is_blocked_ip


class TestIsBlockedIp:
    # --- RFC 1918 Private ---
    def test_loopback_v4(self) -> None:
        assert is_blocked_ip("127.0.0.1") is True

    def test_private_10(self) -> None:
        assert is_blocked_ip("10.0.0.1") is True

    def test_private_172(self) -> None:
        assert is_blocked_ip("172.16.0.1") is True

    def test_private_192(self) -> None:
        assert is_blocked_ip("192.168.1.1") is True

    def test_link_local(self) -> None:
        assert is_blocked_ip("169.254.1.1") is True

    def test_loopback_v6(self) -> None:
        assert is_blocked_ip("::1") is True

    def test_public_ip(self) -> None:
        assert is_blocked_ip("8.8.8.8") is False

    def test_public_ip_v6(self) -> None:
        assert is_blocked_ip("2001:4860:4860::8888") is False

    def test_unparseable_blocks(self) -> None:
        assert is_blocked_ip("not-an-ip") is True

    def test_zero_network(self) -> None:
        assert is_blocked_ip("0.0.0.1") is True

    # --- CGNAT (RFC 6598) ---
    def test_cgnat_blocked(self) -> None:
        assert is_blocked_ip("100.64.0.1") is True

    def test_cgnat_upper_blocked(self) -> None:
        assert is_blocked_ip("100.127.255.254") is True

    # --- TEST-NET (RFC 5737) ---
    def test_test_net_1(self) -> None:
        assert is_blocked_ip("192.0.2.1") is True

    def test_test_net_2(self) -> None:
        assert is_blocked_ip("198.51.100.1") is True

    def test_test_net_3(self) -> None:
        assert is_blocked_ip("203.0.113.1") is True

    # --- Reserved (RFC 6890) ---
    def test_reserved_240(self) -> None:
        assert is_blocked_ip("240.0.0.1") is True

    # --- Multicast ---
    def test_multicast_v4(self) -> None:
        assert is_blocked_ip("224.0.0.1") is True

    def test_multicast_v6(self) -> None:
        assert is_blocked_ip("ff02::1") is True

    # --- Unspecified ---
    def test_unspecified_v4(self) -> None:
        assert is_blocked_ip("0.0.0.0") is True

    def test_unspecified_v6(self) -> None:
        assert is_blocked_ip("::") is True

    # --- Fake-IP Proxy Exemption (198.18.0.0/15) ---
    def test_fake_ip_allowed(self) -> None:
        assert is_blocked_ip("198.18.0.1") is False

    def test_fake_ip_upper_allowed(self) -> None:
        assert is_blocked_ip("198.19.255.254") is False

    # --- IPv6 Private ---
    def test_unique_local_v6(self) -> None:
        assert is_blocked_ip("fc00::1") is True

    def test_link_local_v6(self) -> None:
        assert is_blocked_ip("fe80::1") is True

    # --- IPv4-mapped IPv6 ---
    def test_ipv4_mapped_cgnat(self) -> None:
        assert is_blocked_ip("::ffff:100.64.0.1") is True

    def test_ipv4_mapped_public(self) -> None:
        assert is_blocked_ip("::ffff:8.8.8.8") is False


class TestCheckUrl:
    def test_valid_https(self) -> None:
        v = check_url("https://example.com/path")
        assert v.allowed is True

    def test_valid_http(self) -> None:
        v = check_url("http://example.com")
        assert v.allowed is True

    def test_blocked_scheme_ftp(self) -> None:
        v = check_url("ftp://example.com")
        assert v.allowed is False
        assert "scheme" in v.reason.lower()

    def test_blocked_scheme_file(self) -> None:
        v = check_url("file:///etc/passwd")
        assert v.allowed is False

    def test_blocked_scheme_javascript(self) -> None:
        v = check_url("javascript:alert(1)")
        assert v.allowed is False

    def test_private_ip_in_url(self) -> None:
        v = check_url("http://192.168.1.1/admin")
        assert v.allowed is False
        assert "private" in v.reason.lower() or "internal" in v.reason.lower()

    def test_loopback_in_url(self) -> None:
        v = check_url("http://127.0.0.1:8080")
        assert v.allowed is False

    def test_allowed_internal_host(self) -> None:
        v = check_url("http://127.0.0.1:8080", allowed_internal_hosts=frozenset({"127.0.0.1"}))
        assert v.allowed is True

    def test_no_hostname(self) -> None:
        v = check_url("http://")
        assert v.allowed is False
        assert "hostname" in v.reason.lower()

    def test_domain_name_passes(self) -> None:
        v = check_url("https://api.openai.com/v1/chat")
        assert v.allowed is True

    def test_malformed_url(self) -> None:
        v = check_url("http://[invalid")
        assert v.allowed is True or v.allowed is False  # should not crash

    def test_cgnat_ip_blocked(self) -> None:
        v = check_url("http://100.64.0.1/admin")
        assert v.allowed is False
        assert "private" in v.reason.lower() or "internal" in v.reason.lower()

    def test_multicast_ip_blocked(self) -> None:
        v = check_url("http://224.0.0.1/")
        assert v.allowed is False

    def test_fake_ip_allowed(self) -> None:
        v = check_url("http://198.18.0.1/proxy")
        assert v.allowed is True

    def test_reserved_ip_blocked(self) -> None:
        v = check_url("http://240.0.0.1/")
        assert v.allowed is False


class TestResolveAndCheck:
    def test_allowed_internal_host_bypass(self) -> None:
        v = resolve_and_check("localhost", allowed_internal_hosts=frozenset({"localhost"}))
        assert v.allowed is True

    @patch("socket.getaddrinfo", side_effect=__import__("socket").gaierror("mock DNS failure"))
    def test_dns_failure(self, mock_getaddrinfo: object) -> None:
        v = resolve_and_check("nonexistent.invalid")
        assert v.allowed is False
        assert "dns" in v.reason.lower()

    @patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))])
    def test_public_domain(self, mock_getaddrinfo: object) -> None:
        v = resolve_and_check("example.com")
        assert v.allowed is True

    @patch("socket.getaddrinfo")
    def test_resolves_to_private_ip(self, mock_getaddrinfo: object) -> None:
        mock_getaddrinfo.return_value = [  # type: ignore[attr-defined]
            (2, 1, 6, "", ("192.168.1.1", 0)),
        ]
        v = resolve_and_check("evil.com")
        assert v.allowed is False
        assert "private" in v.reason.lower() or "internal" in v.reason.lower()

    @patch("socket.getaddrinfo")
    def test_resolves_to_cgnat_blocked(self, mock_getaddrinfo: object) -> None:
        mock_getaddrinfo.return_value = [  # type: ignore[attr-defined]
            (2, 1, 6, "", ("100.64.0.1", 0)),
        ]
        v = resolve_and_check("evil.com")
        assert v.allowed is False

    @patch("socket.getaddrinfo")
    def test_resolves_to_fake_ip_allowed(self, mock_getaddrinfo: object) -> None:
        mock_getaddrinfo.return_value = [  # type: ignore[attr-defined]
            (2, 1, 6, "", ("198.18.0.1", 0)),
        ]
        v = resolve_and_check("proxy-domain.com")
        assert v.allowed is True
