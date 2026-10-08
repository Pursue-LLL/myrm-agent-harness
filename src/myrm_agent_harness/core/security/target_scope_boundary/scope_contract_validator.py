"""
[POS] src/myrm_agent_harness/core/security/target_scope_boundary/scope_contract_validator.py
[INPUT] fnmatch, ipaddress, logging, re, typing, .types
[OUTPUT] TargetScopeContractValidator

Validator for Target Scope Rules of Engagement (ROE) contracts and cloud metadata defenses.
Parses IPv4/IPv6 CIDRs, evaluates wildcard subdomains, and enforces explicit exclusions.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import fnmatch
import ipaddress
import logging

from .types import TargetScopeContract

logger = logging.getLogger(__name__)


class TargetScopeContractValidator:
    """Validates destination hosts, domain hierarchies, and IP CIDRs against ROE scope rules."""

    _METADATA_IPS: tuple[str, ...] = (
        "169.254.169.254",
        "fd00:ec2::254",
        "100.100.100.200",  # Alibaba Cloud metadata
    )

    _METADATA_HOSTNAMES: tuple[str, ...] = (
        "instance-data",
        "metadata.google.internal",
        "metadata.tencentyun.com",
    )

    def is_cloud_metadata(self, host_or_ip: str) -> bool:
        """Check if destination matches known cloud provider metadata endpoints."""
        cleaned = host_or_ip.strip().lower()
        return cleaned in self._METADATA_IPS or cleaned in self._METADATA_HOSTNAMES

    def is_domain_in_scope(self, domain: str, contract: TargetScopeContract) -> bool:
        """Check whether destination domain satisfies contract scope and avoids prohibited targets."""
        cleaned = domain.strip().lower()

        if self.is_cloud_metadata(cleaned):
            return False

        # 1. Prohibited target check (explicit blackhole)
        for prohibited in contract.prohibited_targets:
            p_clean = prohibited.strip().lower()
            if self._matches_pattern(cleaned, p_clean):
                logger.warning("Domain '%s' hit prohibited target rule '%s'.", cleaned, prohibited)
                return False

        # 2. Authorized domain check
        for authorized in contract.authorized_domains:
            a_clean = authorized.strip().lower()
            if self._matches_pattern(cleaned, a_clean):
                return True

        return False

    def is_ip_in_scope(self, ip_str: str, contract: TargetScopeContract) -> bool:
        """Check whether destination IP address is within authorized CIDRs and not prohibited."""
        cleaned = ip_str.strip()

        if self.is_cloud_metadata(cleaned):
            return False

        try:
            target_ip = ipaddress.ip_address(cleaned)
        except ValueError:
            logger.warning("Invalid IP string '%s' encountered in scope verification.", ip_str)
            return False

        # 1. Check prohibited IP addresses or subnets
        for prohibited in contract.prohibited_targets:
            try:
                if "/" in prohibited:
                    net = ipaddress.ip_network(prohibited.strip(), strict=False)
                    if target_ip in net:
                        return False
                else:
                    if target_ip == ipaddress.ip_address(prohibited.strip()):
                        return False
            except ValueError:
                continue

        # 2. Check authorized CIDRs
        for cidr in contract.authorized_cidrs:
            try:
                net = ipaddress.ip_network(cidr.strip(), strict=False)
                if target_ip in net:
                    return True
            except ValueError:
                logger.warning("Invalid CIDR '%s' in contract '%s'.", cidr, contract.contract_id)
                continue

        return False

    @staticmethod
    def _matches_pattern(target: str, pattern: str) -> bool:
        """Match domain string against exact or wildcard pattern (e.g., *.example.com)."""
        if target == pattern:
            return True
        if pattern.startswith("*."):
            root = pattern[2:]
            if target == root or target.endswith("." + root):
                return True
        return fnmatch.fnmatch(target, pattern)
