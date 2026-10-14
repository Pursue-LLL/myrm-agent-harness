"""Outbound URL syntax check: what every outbound policy rejects before it looks at the host."""

from __future__ import annotations

import pytest

from myrm_agent_harness.utils.url_syntax import parse_outbound_hostname


@pytest.mark.parametrize(
    ("url", "hostname"),
    [
        ("https://example.com/path", "example.com"),
        ("http://localhost:3000/", "localhost"),  # no blocklist here: a policy that admits private hosts relies on this
        ("http://LOCALHOST./", "localhost"),  # trailing dot stripped and case folded, so blocklists match
        ("http://[::1]:8080/", "::1"),
        ("wss://stream.example.com/", "stream.example.com"),
    ],
)
def test_accepts_http_family_urls_and_returns_the_host(url: str, hostname: str) -> None:
    assert parse_outbound_hostname(url) == (hostname, "")


@pytest.mark.parametrize(
    ("url", "error"),
    [
        ("http://evil.com\t@169.254.169.254/", "parser-confusing"),
        ("http://evil.com\\@169.254.169.254/", "parser-confusing"),
        ("http://evil.com\n.internal/", "parser-confusing"),
        ("file:///etc/passwd", "Blocked URL scheme: file"),
        ("ftp://example.com/", "Blocked URL scheme: ftp"),
        ("gopher://example.com/", "Blocked URL scheme: gopher"),
        ("example.com/no-scheme", "Blocked URL scheme: "),
        ("http:///path", "Missing hostname"),
    ],
)
def test_rejects_urls_a_client_and_a_parser_could_read_differently(url: str, error: str) -> None:
    hostname, message = parse_outbound_hostname(url)

    assert hostname is None
    assert error in message
