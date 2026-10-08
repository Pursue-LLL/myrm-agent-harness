"""Hop evaluation engine for redirect and subresource network security.

[INPUT]
- .types::HopDisposition, HopEvaluationResult, RedirectHopGuardConfig
- stdlib ipaddress, urllib.parse, socket

[OUTPUT]
- RedirectHopEvaluator: evaluates individual network hops against private/metadata policies

[POS]
Pure-python hop safety inspector. Determines whether a URL is an internal,
cloud metadata (IMDS), loopback, or link-local address and assigns disposition.
Strictly avoids Any types; enforced under 400 lines limit.
"""

from __future__ import annotations

import ipaddress
import logging
from urllib.parse import urlparse

from myrm_agent_harness.core.security.redirect_hop_guard.types import (
    HopDisposition,
    HopEvaluationResult,
    RedirectHopGuardConfig,
)

logger = logging.getLogger(__name__)

_CLOUD_METADATA_HOSTS: frozenset[str] = frozenset({
    "169.254.169.254",
    "instance-data",
    "metadata.google.internal",
    "100.100.100.200",  # Alibaba Cloud IMDS
})

_SPECIAL_LOCAL_HOSTNAMES: frozenset[str] = frozenset({
    "localhost",
    "local",
    "loopback",
})

_PRIVATE_HOSTNAME_SUFFIXES: tuple[str, ...] = (
    ".localhost",
    ".local",
    ".lan",
    ".internal",
    ".intranet",
    ".home.arpa",
)

_IPV4_PRIVATE_NETWORKS: tuple[ipaddress.IPv4Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),      # Loopback
    ipaddress.ip_network("10.0.0.0/8"),       # RFC 1918 Class A
    ipaddress.ip_network("172.16.0.0/12"),    # RFC 1918 Class B
    ipaddress.ip_network("192.168.0.0/16"),   # RFC 1918 Class C
    ipaddress.ip_network("169.254.0.0/16"),   # Link-local / AWS/Azure/GCP IMDS
    ipaddress.ip_network("100.64.0.0/10"),    # Carrier-grade NAT
    ipaddress.ip_network("0.0.0.0/8"),        # Current network
)

_IPV6_PRIVATE_NETWORKS: tuple[ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("::1/128"),          # Loopback
    ipaddress.ip_network("fc00::/7"),         # Unique local address (ULA)
    ipaddress.ip_network("fe80::/10"),        # Link-local unicast
)


class RedirectHopEvaluator:
    """Evaluates whether an outgoing hop or redirect targets private or cloud metadata IPs."""

    def __init__(self, config: RedirectHopGuardConfig | None = None) -> None:
        self._config = config or RedirectHopGuardConfig()

    @property
    def config(self) -> RedirectHopGuardConfig:
        return self._config

    def evaluate_hop(self, target_url: str, resource_type: str = "document") -> HopEvaluationResult:
        """Inspect a single request hop and return disposition.

        Args:
            target_url: The destination URL being fetched or redirected to.
            resource_type: Playwright resource type ('document', 'xhr', 'fetch', 'script', etc.).

        Returns:
            HopEvaluationResult detailing safety verdict and rule attribution.
        """
        if self._config.allow_private_networks:
            return HopEvaluationResult(
                disposition=HopDisposition.ALLOW,
                is_private=False,
                matched_rule="ALLOW_POLICY_ENABLED",
                target_url=target_url,
                resource_type=resource_type,
                reason="Private networks are explicitly permitted by policy configuration",
            )

        if not target_url.startswith(("http://", "https://")):
            # Non-http protocols (data, file, javascript, about)
            if resource_type == "document" and not target_url.startswith("about:"):
                return HopEvaluationResult(
                    disposition=HopDisposition.ABORT_AND_RESET_DOCUMENT,
                    is_private=True,
                    matched_rule="NON_HTTP_DOCUMENT_BLOCKED",
                    target_url=target_url,
                    resource_type=resource_type,
                    reason=f"Non-HTTP scheme blocked for top-level document: {target_url}",
                )
            return HopEvaluationResult(
                disposition=HopDisposition.ALLOW,
                is_private=False,
                matched_rule="NON_HTTP_SAFE",
                target_url=target_url,
                resource_type=resource_type,
                reason="Non-HTTP subresource allowed or about: URL",
            )

        try:
            parsed = urlparse(target_url)
            hostname = (parsed.hostname or "").strip().lower().rstrip(".")
        except Exception as exc:
            return HopEvaluationResult(
                disposition=self._get_blocked_disposition(resource_type),
                is_private=True,
                matched_rule="MALFORMED_URL",
                target_url=target_url,
                resource_type=resource_type,
                reason=f"Failed to parse target URL: {exc}",
            )

        if not hostname:
            return HopEvaluationResult(
                disposition=self._get_blocked_disposition(resource_type),
                is_private=True,
                matched_rule="EMPTY_HOSTNAME",
                target_url=target_url,
                resource_type=resource_type,
                reason="Target URL lacks a valid hostname",
            )

        # 1. Cloud metadata hostnames check (highest priority IMDS attribution)
        if hostname in _CLOUD_METADATA_HOSTS:
            return self._build_blocked_result(
                target_url=target_url,
                resource_type=resource_type,
                rule="CLOUD_METADATA_IMDS",
                reason=f"Target host '{hostname}' is a known Cloud Instance Metadata Service (IMDS)",
            )

        # 2. Custom blocked hostnames check
        if hostname in self._config.custom_blocked_hostnames:
            return self._build_blocked_result(
                target_url=target_url,
                resource_type=resource_type,
                rule="CUSTOM_BLOCKED_HOST",
                reason=f"Target hostname '{hostname}' is in the custom blocked hostnames list",
            )

        # 3. Special local hostnames & suffix patterns
        if hostname in _SPECIAL_LOCAL_HOSTNAMES or any(hostname.endswith(s) for s in _PRIVATE_HOSTNAME_SUFFIXES):
            return self._build_blocked_result(
                target_url=target_url,
                resource_type=resource_type,
                rule="LOCAL_HOSTNAME_PATTERN",
                reason=f"Target host '{hostname}' matches private/local domain pattern",
            )

        # 4. Direct IP address check
        try:
            ip_obj = ipaddress.ip_address(hostname)
            ip_check = self._check_ip_address(ip_obj)
            if ip_check is not None:
                rule_name, reason_msg = ip_check
                return self._build_blocked_result(
                    target_url=target_url,
                    resource_type=resource_type,
                    rule=rule_name,
                    reason=reason_msg,
                )
        except ValueError:
            # Not a literal IP, hostname will be resolved during connection
            pass

        return HopEvaluationResult(
            disposition=HopDisposition.ALLOW,
            is_private=False,
            matched_rule="PUBLIC_TARGET",
            target_url=target_url,
            resource_type=resource_type,
            reason="Target URL does not match any private or metadata patterns",
        )

    def _get_blocked_disposition(self, resource_type: str) -> HopDisposition:
        if resource_type == "document" and self._config.reset_to_about_blank:
            return HopDisposition.ABORT_AND_RESET_DOCUMENT
        return HopDisposition.ABORT_SUBRESOURCE

    def _build_blocked_result(
        self,
        target_url: str,
        resource_type: str,
        rule: str,
        reason: str,
    ) -> HopEvaluationResult:
        return HopEvaluationResult(
            disposition=self._get_blocked_disposition(resource_type),
            is_private=True,
            matched_rule=rule,
            target_url=target_url,
            resource_type=resource_type,
            reason=reason,
        )

    def _check_ip_address(
        self,
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
    ) -> tuple[str, str] | None:
        """Check if an IP address belongs to blocked private/link-local/IMDS ranges."""
        if isinstance(ip, ipaddress.IPv4Address):
            # Special check for 169.254.169.254
            if str(ip) == "169.254.169.254":
                return "CLOUD_METADATA_IMDS", "IP 169.254.169.254 is the cloud instance metadata endpoint"
            for net in _IPV4_PRIVATE_NETWORKS:
                if ip in net:
                    return f"PRIVATE_IPV4_{net}", f"IP {ip} belongs to private/link-local network {net}"
        elif isinstance(ip, ipaddress.IPv6Address):
            # IPv4 mapped IPv6 (e.g., ::ffff:169.254.169.254)
            if ip.ipv4_mapped is not None:
                return self._check_ip_address(ip.ipv4_mapped)
            for v6_net in _IPV6_PRIVATE_NETWORKS:
                if ip in v6_net:
                    return f"PRIVATE_IPV6_{v6_net}", f"IPv6 {ip} belongs to private network {v6_net}"
        return None
