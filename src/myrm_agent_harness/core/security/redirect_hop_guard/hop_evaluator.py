"""Hop evaluation engine for redirect and subresource network security.

[INPUT]
- .types::HopDisposition, HopEvaluationResult
- .origin_grants::PrivateOriginGrants (POS: set of origins that may be loaded although they are private)
- .name_resolution::IPAddress, resolve_addresses (POS: bounded, briefly cached hostname lookup)
- stdlib ipaddress, urllib.parse

[OUTPUT]
- RedirectHopEvaluator: evaluates individual network hops against private/metadata policies

[POS]
Hop safety inspector. ``evaluate_hop`` classifies the literal host of a URL as internal, cloud
metadata (IMDS), loopback or link-local and assigns a disposition without any DNS.
``evaluate_hop_resolved`` is the local-mode entry point: it also looks a plain hostname up, so a name
that points at loopback, link-local or a metadata endpoint is judged like the address it spells.
Shared by the browser context filter, the navigation guard and the web_fetch local-mode guard.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from myrm_agent_harness.core.security.redirect_hop_guard.name_resolution import IPAddress, resolve_addresses
from myrm_agent_harness.core.security.redirect_hop_guard.origin_grants import PrivateOriginGrants
from myrm_agent_harness.core.security.redirect_hop_guard.types import HopDisposition, HopEvaluationResult

_PUBLIC_TARGET = "PUBLIC_TARGET"

_CLOUD_METADATA_ADDRESSES: frozenset[IPAddress] = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),  # AWS / Azure / GCP IMDS
        ipaddress.ip_address("100.100.100.200"),  # Alibaba Cloud IMDS
    }
)

_CLOUD_METADATA_HOSTS: frozenset[str] = frozenset(
    {"instance-data", "metadata.google.internal", *(str(address) for address in _CLOUD_METADATA_ADDRESSES)}
)

_SPECIAL_LOCAL_HOSTNAMES: frozenset[str] = frozenset(
    {
        "localhost",
        "local",
        "loopback",
    }
)

_PRIVATE_HOSTNAME_SUFFIXES: tuple[str, ...] = (
    ".localhost",
    ".local",
    ".lan",
    ".internal",
    ".intranet",
    ".home.arpa",
)

_IPV4_PRIVATE_NETWORKS: tuple[ipaddress.IPv4Network, ...] = (
    ipaddress.IPv4Network("127.0.0.0/8"),  # Loopback
    ipaddress.IPv4Network("10.0.0.0/8"),  # RFC 1918 Class A
    ipaddress.IPv4Network("172.16.0.0/12"),  # RFC 1918 Class B
    ipaddress.IPv4Network("192.168.0.0/16"),  # RFC 1918 Class C
    ipaddress.IPv4Network("169.254.0.0/16"),  # Link-local / AWS/Azure/GCP IMDS
    ipaddress.IPv4Network("100.64.0.0/10"),  # Carrier-grade NAT
    ipaddress.IPv4Network("0.0.0.0/8"),  # Current network
)

_IPV6_PRIVATE_NETWORKS: tuple[ipaddress.IPv6Network, ...] = (
    ipaddress.IPv6Network("::1/128"),  # Loopback
    ipaddress.IPv6Network("fc00::/7"),  # Unique local address (ULA)
    ipaddress.IPv6Network("fe80::/10"),  # Link-local unicast
)


class RedirectHopEvaluator:
    """Evaluates whether an outgoing hop or redirect targets private or cloud metadata IPs.

    ``grants`` relaxes the private-network rules (loopback, LAN, local names) for origins the agent
    navigated to on purpose. Cloud metadata endpoints are never relaxed.
    """

    def __init__(self, grants: PrivateOriginGrants | None = None) -> None:
        self._grants = grants

    def evaluate_hop(self, target_url: str, resource_type: str = "document") -> HopEvaluationResult:
        """Inspect a single request hop and return disposition.

        Args:
            target_url: The destination URL being fetched or redirected to.
            resource_type: Playwright resource type ('document', 'xhr', 'fetch', 'script', etc.).

        Returns:
            HopEvaluationResult detailing safety verdict and rule attribution.
        """
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

        # 2. Special local hostnames & suffix patterns
        if hostname in _SPECIAL_LOCAL_HOSTNAMES or any(hostname.endswith(s) for s in _PRIVATE_HOSTNAME_SUFFIXES):
            return self._blocked_unless_granted(
                target_url=target_url,
                resource_type=resource_type,
                rule="LOCAL_HOSTNAME_PATTERN",
                reason=f"Target host '{hostname}' matches private/local domain pattern",
            )

        # 3. Direct IP address check
        try:
            ip_obj = ipaddress.ip_address(hostname)
            ip_check = self._check_ip_address(ip_obj)
            if ip_check is not None:
                rule_name, reason_msg = ip_check
                if rule_name == "CLOUD_METADATA_IMDS":
                    return self._build_blocked_result(target_url, resource_type, rule_name, reason_msg)
                return self._blocked_unless_granted(target_url, resource_type, rule_name, reason_msg)
        except ValueError:
            # Not a literal IP, hostname will be resolved during connection
            pass

        return HopEvaluationResult(
            disposition=HopDisposition.ALLOW,
            is_private=False,
            matched_rule=_PUBLIC_TARGET,
            target_url=target_url,
            resource_type=resource_type,
            reason="Target URL does not match any private or metadata patterns",
        )

    async def evaluate_hop_resolved(self, target_url: str, resource_type: str = "document") -> HopEvaluationResult:
        """``evaluate_hop`` plus one name lookup for a plain hostname that looked public.

        Only local-mode policies (grants given) look names up. The cloud policy resolves and pins
        only entry navigations and web fetches (``async_pin_url``, ``FetchTargetGuard``), so its
        redirect hops and subresources are judged by the literal host alone. Only loopback,
        link-local, unspecified and cloud metadata answers are judged. RFC 1918, CGNAT and
        benchmarking ranges are not, because fake-IP proxies and VPNs hand them out for public
        names. A lookup that fails or times out judges nothing.
        """
        verdict = self.evaluate_hop(target_url, resource_type)
        if self._grants is None or verdict.matched_rule != _PUBLIC_TARGET:
            return verdict
        hostname = _plain_hostname(target_url)
        if hostname is None:
            return verdict
        addresses = [_unmapped(address) for address in await resolve_addresses(hostname)]
        metadata = next((address for address in addresses if address in _CLOUD_METADATA_ADDRESSES), None)
        if metadata is not None:
            return self._build_blocked_result(
                target_url,
                resource_type,
                "CLOUD_METADATA_IMDS",
                f"Target host '{hostname}' resolves to {metadata}, a cloud instance metadata endpoint",
            )
        local = next((address for address in addresses if _is_local_address(address)), None)
        if local is not None:
            return self._blocked_unless_granted(
                target_url,
                resource_type,
                "RESOLVES_TO_LOCAL_ADDRESS",
                f"Target host '{hostname}' resolves to {local}, a loopback or link-local address",
            )
        return verdict

    @staticmethod
    def _get_blocked_disposition(resource_type: str) -> HopDisposition:
        if resource_type == "document":
            return HopDisposition.ABORT_AND_RESET_DOCUMENT
        return HopDisposition.ABORT_SUBRESOURCE

    def _blocked_unless_granted(
        self,
        target_url: str,
        resource_type: str,
        rule: str,
        reason: str,
    ) -> HopEvaluationResult:
        if self._grants is not None and self._grants.permits(target_url):
            return HopEvaluationResult(
                disposition=HopDisposition.ALLOW,
                is_private=True,
                matched_rule="EXPLICIT_PRIVATE_ORIGIN",
                target_url=target_url,
                resource_type=resource_type,
                reason=f"Origin was navigated to explicitly; would otherwise match {rule}",
            )
        return self._build_blocked_result(target_url, resource_type, rule, reason)

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
            if ip in _CLOUD_METADATA_ADDRESSES:
                return "CLOUD_METADATA_IMDS", f"IP {ip} is a cloud instance metadata endpoint"
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


def _plain_hostname(target_url: str) -> str | None:
    """The normalised host of an http(s) URL, or None when it is an IP literal (nothing to look up)."""
    hostname = (urlparse(target_url).hostname or "").strip().lower().rstrip(".")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return hostname
    return None


def _unmapped(address: IPAddress) -> IPAddress:
    """The IPv4 address inside an IPv4-mapped IPv6 answer; any other address unchanged."""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _is_local_address(address: IPAddress) -> bool:
    return address.is_loopback or address.is_link_local or address.is_unspecified
