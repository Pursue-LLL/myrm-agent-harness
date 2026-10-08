"""
[POS] src/myrm_agent_harness/core/security/hardened_sandbox_perimeter/ssrf_egress_shield.py
[INPUT] ipaddress, socket, typing, .types (EgressTarget, EgressEvaluationResult, EgressVerdictEnum)
[OUTPUT] SsrfEgressShield

Enforces zero-trust outbound network boundaries and SSRF interception.
Strictly blocks access to RFC 1918 private subnets, loopback interfaces,
cloud provider metadata endpoints (169.254.169.254), and un-whitelisted domains.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable

from .types import EgressEvaluationResult, EgressTarget, EgressVerdictEnum

# Blocked IPv4 networks
_BLOCKED_IPV4_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("255.255.255.255/32"),
]

# Blocked IPv6 networks
_BLOCKED_IPV6_NETWORKS = [
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fc00::/7"),
]

_CLOUD_METADATA_IP = ipaddress.ip_address("169.254.169.254")


class SsrfEgressShield:
    """Zero-trust perimeter firewall preventing SSRF and lateral movement out of sandbox."""

    def __init__(
        self,
        resolver_fn: Callable[[str], list[str]] | None = None,
    ) -> None:
        """Initialize with optional custom resolver for deterministic testing."""
        self._resolver_fn = resolver_fn or self._default_resolve

    @staticmethod
    def _default_resolve(hostname: str) -> list[str]:
        """Resolve hostname to list of IP addresses using socket."""
        try:
            _, _, ip_addresses = socket.gethostbyname_ex(hostname)
            return ip_addresses
        except (socket.gaierror, socket.herror, OSError):
            return []

    def evaluate_egress(
        self,
        target: EgressTarget,
        allowlisted_domains: list[str] | None = None,
    ) -> EgressEvaluationResult:
        """Evaluate an outbound connection request against strict anti-SSRF policies."""
        host = target.host.strip().lower()
        if not host:
            return EgressEvaluationResult(
                is_allowed=False,
                verdict=EgressVerdictEnum.BLOCKED_INVALID_HOST,
                reason="Target host string cannot be empty.",
            )

        # 1. Check if host is direct IP address
        try:
            ip_obj = ipaddress.ip_address(host)
            return self._evaluate_ip_address(ip_obj)
        except ValueError:
            # Host is a domain name
            pass

        # 2. Check domain allowlist if configured
        if allowlisted_domains is not None and len(allowlisted_domains) > 0:
            is_domain_allowed = False
            for allowed in allowlisted_domains:
                allowed_clean = allowed.strip().lower()
                if host == allowed_clean or host.endswith(f".{allowed_clean}"):
                    is_domain_allowed = True
                    break
            if not is_domain_allowed:
                return EgressEvaluationResult(
                    is_allowed=False,
                    verdict=EgressVerdictEnum.BLOCKED_DOMAIN_NOT_ALLOWLISTED,
                    reason=f"Domain '{host}' is not present in egress allowlist.",
                )

        # 3. Resolve domain name to IP addresses
        resolved_ips = self._resolver_fn(host)
        if not resolved_ips:
            return EgressEvaluationResult(
                is_allowed=False,
                verdict=EgressVerdictEnum.BLOCKED_INVALID_HOST,
                reason=f"Failed to resolve host '{host}' via DNS.",
            )

        # 4. Validate every resolved IP against blocked networks (DNS rebinding protection)
        for ip_str in resolved_ips:
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                ip_eval = self._evaluate_ip_address(ip_obj)
                if not ip_eval.is_allowed:
                    return EgressEvaluationResult(
                        is_allowed=False,
                        verdict=ip_eval.verdict,
                        reason=f"Domain '{host}' resolved to restricted address {ip_str}: {ip_eval.reason}",
                        resolved_ip=ip_str,
                    )
            except ValueError:
                return EgressEvaluationResult(
                    is_allowed=False,
                    verdict=EgressVerdictEnum.BLOCKED_INVALID_HOST,
                    reason=f"Resolved invalid IP '{ip_str}' for host '{host}'.",
                )

        # Outbound traffic satisfies all zero-trust criteria
        return EgressEvaluationResult(
            is_allowed=True,
            verdict=EgressVerdictEnum.ALLOWED,
            reason=f"Outbound connection to '{host}:{target.port}' is permitted.",
            resolved_ip=resolved_ips[0] if resolved_ips else None,
        )

    def _evaluate_ip_address(
        self, ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address
    ) -> EgressEvaluationResult:
        """Check whether an IP address belongs to blocked subnets or metadata endpoints."""
        # Cloud metadata intercept
        if ip_obj == _CLOUD_METADATA_IP:
            return EgressEvaluationResult(
                is_allowed=False,
                verdict=EgressVerdictEnum.BLOCKED_CLOUD_METADATA,
                reason="Direct connection to cloud instance metadata service (169.254.169.254) is prohibited.",
                resolved_ip=str(ip_obj),
            )

        if isinstance(ip_obj, ipaddress.IPv4Address):
            for network in _BLOCKED_IPV4_NETWORKS:
                if ip_obj in network:
                    return EgressEvaluationResult(
                        is_allowed=False,
                        verdict=EgressVerdictEnum.BLOCKED_PRIVATE_IP,
                        reason=f"IPv4 address {ip_obj} falls within prohibited network {network}.",
                        resolved_ip=str(ip_obj),
                    )

        if isinstance(ip_obj, ipaddress.IPv6Address):
            for network in _BLOCKED_IPV6_NETWORKS:
                if ip_obj in network:
                    return EgressEvaluationResult(
                        is_allowed=False,
                        verdict=EgressVerdictEnum.BLOCKED_PRIVATE_IP,
                        reason=f"IPv6 address {ip_obj} falls within prohibited network {network}.",
                        resolved_ip=str(ip_obj),
                    )

        return EgressEvaluationResult(
            is_allowed=True,
            verdict=EgressVerdictEnum.ALLOWED,
            reason=f"IP address {ip_obj} is a valid routable public destination.",
            resolved_ip=str(ip_obj),
        )
