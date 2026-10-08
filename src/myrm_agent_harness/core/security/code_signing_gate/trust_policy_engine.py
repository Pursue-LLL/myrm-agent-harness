"""
[POS] src/myrm_agent_harness/core/security/code_signing_gate/trust_policy_engine.py
[INPUT] threading, typing, .types (DeveloperCertificateInfo, PackageVerificationVerdictEnum, SupplyChainTrustPolicyEnum)
[OUTPUT] SupplyChainTrustPolicyEngine

Evaluates agent package signatures and developer certificates against configurable
enterprise supply chain trust policies (STRICT_ENTERPRISE_ONLY, VERIFIED_CA_ONLY,
ALLOW_COMMUNITY_WARNING, DENY_ALL) and certificate revocation lists.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import threading

from .types import (
    DeveloperCertificateInfo,
    PackageVerificationVerdictEnum,
    SupplyChainTrustPolicyEnum,
)


class SupplyChainTrustPolicyEngine:
    """Configurable enterprise policy gate enforcing organizational supply chain rules."""

    def __init__(
        self,
        default_policy: SupplyChainTrustPolicyEnum = SupplyChainTrustPolicyEnum.VERIFIED_CA_ONLY,
    ) -> None:
        self._lock = threading.Lock()
        self._policy = default_policy
        self._trusted_cas: set[str] = {
            "GuizhouCA",
            "GlobalSign",
            "DigiCert",
            "EnterpriseRootCA",
        }
        self._revoked_serials: set[str] = set()

    def get_policy(self) -> SupplyChainTrustPolicyEnum:
        """Get currently active enterprise trust policy."""
        with self._lock:
            return self._policy

    def set_policy(self, policy: SupplyChainTrustPolicyEnum) -> None:
        """Update enterprise supply chain trust policy."""
        with self._lock:
            self._policy = policy

    def add_trusted_ca(self, ca_name: str) -> None:
        """Add an authorized Certificate Authority to the trust store."""
        with self._lock:
            self._trusted_cas.add(ca_name)

    def revoke_certificate(self, cert_serial: str) -> None:
        """Add certificate serial to revocation list."""
        with self._lock:
            self._revoked_serials.add(cert_serial)

    def evaluate_trust(
        self,
        cert_info: DeveloperCertificateInfo | None,
    ) -> tuple[bool, PackageVerificationVerdictEnum, str]:
        """Assess whether a package's developer credential satisfies active enterprise policy."""
        with self._lock:
            policy = self._policy
            trusted_cas = set(self._trusted_cas)
            revoked_serials = set(self._revoked_serials)

        # Policy: DENY_ALL
        if policy == SupplyChainTrustPolicyEnum.DENY_ALL:
            return False, PackageVerificationVerdictEnum.POLICY_REJECTED, "Enterprise policy blocks all external packages."

        # Unsigned community package handling
        if cert_info is None:
            if policy == SupplyChainTrustPolicyEnum.ALLOW_COMMUNITY_WARNING:
                return (
                    True,
                    PackageVerificationVerdictEnum.UNSIGNED_COMMUNITY,
                    "Package is unsigned; permitted in quarantined sandbox with community warning.",
                )
            return (
                False,
                PackageVerificationVerdictEnum.POLICY_REJECTED,
                f"Unsigned packages are rejected under policy {policy.value}.",
            )

        # Check CRL (Revoked certificate)
        if cert_info.cert_serial in revoked_serials:
            return (
                False,
                PackageVerificationVerdictEnum.REVOKED_CERTIFICATE,
                f"Developer certificate {cert_info.cert_serial} has been revoked.",
            )

        # Check Trusted CA issuer
        if cert_info.issuer_ca not in trusted_cas:
            return (
                False,
                PackageVerificationVerdictEnum.POLICY_REJECTED,
                f"Issuer CA '{cert_info.issuer_ca}' is not recognized in enterprise trust store.",
            )

        # Policy: STRICT_ENTERPRISE_ONLY
        if (
            policy == SupplyChainTrustPolicyEnum.STRICT_ENTERPRISE_ONLY
            and not cert_info.is_internal_enterprise
        ):
            return (
                False,
                PackageVerificationVerdictEnum.POLICY_REJECTED,
                "Only internal enterprise developer-signed packages are permitted under STRICT_ENTERPRISE_ONLY.",
            )

        return (
            True,
            PackageVerificationVerdictEnum.VERIFIED,
            f"Package verified from developer '{cert_info.developer_name}' ({cert_info.org_dn}).",
        )
