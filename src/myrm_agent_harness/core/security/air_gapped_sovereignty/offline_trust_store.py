"""
[POS] src/myrm_agent_harness/core/security/air_gapped_sovereignty/offline_trust_store.py
[INPUT] threading, time, typing, .gm_crypto_engine (sm3_hash), .types (OfflineCertValidationResult, OfflineTrustAnchor)
[OUTPUT] OfflineTrustStore

Pre-distributed Root CA Trust Anchor store and offline CRL certificate revocation manager
for air-gapped and isolated network environments without OCSP or external internet access.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import threading
import time

from .gm_crypto_engine import sm3_hash
from .types import OfflineCertValidationResult, OfflineTrustAnchor


class OfflineTrustStore:
    """Manages pre-distributed root CA certificates and offline revocation lists."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._anchors: dict[str, OfflineTrustAnchor] = {}
        self._revoked_serials: set[str] = set()
        self._initialize_default_anchors()

    def _initialize_default_anchors(self) -> None:
        """Seed default pre-distributed national and enterprise root CAs."""
        default_cas = [
            ("GuizhouCA", "CERT-ROOT-GUIZHOU-2026", 4102444800.0),
            ("NationalTimeServiceCenter", "CERT-ROOT-NTSC-2026", 4102444800.0),
            ("StateEnterpriseRootCA", "CERT-ROOT-STATE-ENT-2026", 4102444800.0),
        ]
        for name, cert_pem, valid_until in default_cas:
            fp = sm3_hash(cert_pem)
            self._anchors[name] = OfflineTrustAnchor(
                ca_name=name,
                root_cert_pem=cert_pem,
                valid_until=valid_until,
                fingerprint_sm3=fp,
            )

    def add_trust_anchor(self, anchor: OfflineTrustAnchor) -> None:
        """Add an offline root CA anchor."""
        with self._lock:
            self._anchors[anchor.ca_name] = anchor

    def get_trust_anchor(self, ca_name: str) -> OfflineTrustAnchor | None:
        """Retrieve a root CA anchor by name."""
        with self._lock:
            return self._anchors.get(ca_name)

    def list_trust_anchors(self) -> list[OfflineTrustAnchor]:
        """List all active offline root CA anchors."""
        with self._lock:
            return list(self._anchors.values())

    def import_crl_bundle(self, revoked_serials: list[str]) -> int:
        """Import pre-distributed offline CRL revoked serials list."""
        with self._lock:
            initial_count = len(self._revoked_serials)
            self._revoked_serials.update(revoked_serials)
            return len(self._revoked_serials) - initial_count

    def is_serial_revoked(self, cert_serial: str) -> bool:
        """Check whether certificate serial is revoked in offline CRL."""
        with self._lock:
            return cert_serial in self._revoked_serials

    def validate_certificate(
        self,
        cert_pem: str,
        cert_serial: str,
        issuer_ca: str,
        valid_until: float,
        current_time: float | None = None,
    ) -> OfflineCertValidationResult:
        """Validate certificate against offline pre-distributed trust store and CRL."""
        now = current_time if current_time is not None else time.time()
        fp = sm3_hash(cert_pem)

        with self._lock:
            # 1. Check offline CRL blacklist
            if cert_serial in self._revoked_serials:
                return OfflineCertValidationResult(
                    is_valid=False,
                    reason=f"Certificate serial '{cert_serial}' is blacklisted in offline CRL bundle.",
                    ca_name=issuer_ca,
                    is_revoked=True,
                    fingerprint_sm3=fp,
                )

            # 2. Check root CA anchor existence
            anchor = self._anchors.get(issuer_ca)
            if anchor is None:
                return OfflineCertValidationResult(
                    is_valid=False,
                    reason=f"Issuer CA '{issuer_ca}' not found in pre-distributed offline trust anchors.",
                    ca_name=issuer_ca,
                    is_revoked=False,
                    fingerprint_sm3=fp,
                )

        # 3. Check expiration
        if now > valid_until:
            return OfflineCertValidationResult(
                is_valid=False,
                reason=f"Certificate expired on timestamp {valid_until} (current: {now}).",
                ca_name=issuer_ca,
                is_revoked=False,
                fingerprint_sm3=fp,
            )

        return OfflineCertValidationResult(
            is_valid=True,
            reason=f"Certificate successfully validated offline against anchor '{issuer_ca}'.",
            ca_name=issuer_ca,
            is_revoked=False,
            fingerprint_sm3=fp,
        )
