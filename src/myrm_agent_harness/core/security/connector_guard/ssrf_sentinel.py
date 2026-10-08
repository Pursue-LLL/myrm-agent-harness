"""SSRF Anomaly Sentinel and Credential Exfiltration Detector."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import parse_qs, urlsplit

from .types import ThreatKind

_METADATA_HOSTS = frozenset(
    {
        "169.254.169.254",
        "metadata.google.internal",
        "instance-data",
        "metadata.packet.net",
    }
)

_SENSITIVE_KEY_NAMES = frozenset(
    {
        "token",
        "auth",
        "key",
        "secret",
        "api_key",
        "apikey",
        "access_token",
        "bearer",
        "credential",
        "password",
        "private_key",
    }
)

_KNOWN_TOKEN_PREFIX_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"gho_[A-Za-z0-9]{36}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{22,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"xoxb-[0-9]+-[A-Za-z0-9]+"),
    re.compile(r"ey[A-Za-z0-9-_]{10,}\.[A-Za-z0-9-_]{10,}\.[A-Za-z0-9-_]{10,}"),  # JWT
]


class SsrfAnomalySentinel:
    """Detects SSRF attempts, private IP probes, host spoofing, and credential smuggling in outbound requests."""

    def __init__(self, block_private_ips: bool = True) -> None:
        self.block_private_ips = block_private_ips

    def check_url(self, raw_url: str) -> tuple[ThreatKind | None, str]:
        """Inspect URL for SSRF, metadata access, host spoofing, or token smuggling."""
        if not raw_url or not raw_url.strip():
            return ThreatKind.HOST_SPOOFING, "Empty or invalid URL"

        try:
            split_result = urlsplit(raw_url)
        except Exception as exc:
            return ThreatKind.HOST_SPOOFING, f"Malformed URL syntax: {exc}"

        host = split_result.hostname
        if not host:
            return ThreatKind.HOST_SPOOFING, "Missing hostname in URL"

        normalized_host = host.lower().strip()

        # 1. Cloud Metadata Probe Check
        if normalized_host in _METADATA_HOSTS:
            return (
                ThreatKind.SSRF_METADATA,
                f"Attempted access to cloud instance metadata endpoint '{normalized_host}'",
            )

        # 2. Userinfo URL Spoofing Check (e.g. https://trusted.com@attacker.com)
        if split_result.username or split_result.password:
            return (
                ThreatKind.HOST_SPOOFING,
                "URL contains embedded userinfo/credentials in authority segment",
            )

        # 3. IP Literal and Subnet SSRF Verification
        ip_threat, ip_reason = self._check_ip_literal(normalized_host)
        if ip_threat is not None:
            return ip_threat, ip_reason

        # 4. Localhost and Loopback Hostnames
        if normalized_host in ("localhost", "localhost.localdomain") or normalized_host.endswith(".localhost"):
            return ThreatKind.SSRF_PRIVATE_IP, f"Target host '{normalized_host}' resolves to local loopback"

        # 5. Token Smuggling in Query String or URL Path
        smuggle_threat, smuggle_reason = self._check_token_smuggling(split_result.query, split_result.path)
        if smuggle_threat is not None:
            return smuggle_threat, smuggle_reason

        return None, ""

    def _check_ip_literal(self, host: str) -> tuple[ThreatKind | None, str]:
        """Verify whether host is an IP literal targeting private, loopback, or link-local ranges."""
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return None, ""  # Not an IP literal, it's a domain name

        if str(ip) == "169.254.169.254":
            return ThreatKind.SSRF_METADATA, "Direct probe to AWS/cloud metadata IP (169.254.169.254)"

        if ip.is_loopback:
            return ThreatKind.SSRF_PRIVATE_IP, f"IP address '{ip}' is a loopback address"

        if ip.is_link_local:
            return ThreatKind.SSRF_METADATA, f"IP address '{ip}' is in link-local metadata range"

        if self.block_private_ips and ip.is_private:
            return ThreatKind.SSRF_PRIVATE_IP, f"IP address '{ip}' belongs to a private RFC1918/RFC4193 subnet"

        if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return ThreatKind.SSRF_PRIVATE_IP, f"IP address '{ip}' is reserved or non-routable"

        return None, ""

    def _check_token_smuggling(
        self, query_string: str, path: str
    ) -> tuple[ThreatKind | None, str]:
        """Inspect query parameters and path for smuggled API tokens or secrets."""
        if not query_string and not path:
            return None, ""

        if query_string:
            params = parse_qs(query_string, keep_blank_values=False)
            for param_key, param_values in params.items():
                lower_key = param_key.lower()
                for val in param_values:
                    # Check known token signatures
                    for pattern in _KNOWN_TOKEN_PREFIX_PATTERNS:
                        if pattern.search(val):
                            return (
                                ThreatKind.TOKEN_SMUGGLING,
                                f"Smuggled token signature detected in query param '{param_key}'",
                            )
                    # Check sensitive param names with high-entropy values
                    if lower_key in _SENSITIVE_KEY_NAMES and len(val) >= 20:
                        return (
                            ThreatKind.TOKEN_SMUGGLING,
                            f"Suspicious high-entropy credential smuggled in query param '{param_key}'",
                        )

        # Check path segments for obvious API keys or tokens embedded directly in URL path
        for pattern in _KNOWN_TOKEN_PREFIX_PATTERNS:
            if pattern.search(path):
                return (
                    ThreatKind.TOKEN_SMUGGLING,
                    "Smuggled secret token signature detected in URL path",
                )

        return None, ""
