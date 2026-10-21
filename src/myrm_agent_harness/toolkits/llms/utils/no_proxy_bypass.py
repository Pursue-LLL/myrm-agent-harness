"""Local and LAN endpoint proxy bypass manager.

Automatically detects localhost, RFC 1918 private subnets, and local domain suffixes,
ensuring local Ollama/vLLM embedding endpoints bypass HTTP_PROXY hijackings.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- LanEndpointNoProxyManager: Manages automatic proxy bypass for local and private LAN endpoints.

[POS]
Local and LAN endpoint proxy bypass manager.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from urllib.parse import urlparse

_LOCAL_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})  # noqa: S104
_LOCAL_DOMAIN_SUFFIXES = (".local", ".internal", ".lan", ".home.arpa")


class LanEndpointNoProxyManager:
    """Manages automatic proxy bypass for local and private LAN endpoints."""

    @classmethod
    def is_local_or_lan_endpoint(cls, url_or_host: str) -> bool:
        """Determine whether the target URL or hostname is local or within private LAN."""
        if not url_or_host or not url_or_host.strip():
            return False

        candidate = url_or_host.strip()
        hostname: str
        if "://" in candidate:
            parsed = urlparse(candidate)
            hostname = parsed.hostname or ""
        else:
            # Might be host:port or bare host
            if ":" in candidate and not candidate.startswith("[") and candidate.count(":") == 1:
                hostname = candidate.split(":", 1)[0]
            else:
                hostname = candidate

        normalized_host = hostname.strip().lower().strip("[]")
        if not normalized_host:
            return False

        # 1. Match well-known local names
        if normalized_host in _LOCAL_HOSTNAMES:
            return True

        # 2. Match local / private domain suffixes
        if any(normalized_host.endswith(suffix) for suffix in _LOCAL_DOMAIN_SUFFIXES):
            return True

        # 3. Match IP address subnets (RFC 1918, Loopback, Link-Local)
        try:
            ip_obj = ipaddress.ip_address(normalized_host)
            return bool(ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local)
        except ValueError:
            # Not a raw IP literal; regular domain name
            pass

        return False

    @classmethod
    def build_recommended_no_proxy_entries(
        cls,
        custom_entries: Sequence[str] | None = None,
    ) -> list[str]:
        """Build standard NO_PROXY entries including local and RFC 1918 CIDRs."""
        base_entries = [
            "localhost",
            "127.0.0.1",
            "::1",
            ".local",
            ".internal",
            ".lan",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
        ]
        if custom_entries:
            for entry in custom_entries:
                cleaned = entry.strip()
                if cleaned and cleaned not in base_entries:
                    base_entries.append(cleaned)
        return base_entries

    @classmethod
    def configure_bypass_client_kwargs(
        cls,
        url: str,
        client_kwargs: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Inject trust_env=False if URL is local or private LAN, preventing proxy hijacking."""
        result = dict(client_kwargs or {})
        if cls.is_local_or_lan_endpoint(url):
            result["trust_env"] = False
        return result
