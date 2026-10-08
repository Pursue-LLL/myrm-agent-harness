"""
[POS] src/myrm_agent_harness/core/security/air_gapped_sovereignty/facade.py
[INPUT] threading, typing, .evidentiary_archive_packer, .gm_crypto_engine, .offline_trust_store, .sovereign_model_fallback, .types
[OUTPUT] AirGappedSovereigntyFacade

Unified Facade for Air-Gapped Offline Trust Store and Sovereign Model Fallback Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import threading

from .evidentiary_archive_packer import EvidentiaryArchivePacker
from .gm_crypto_engine import sm3_hash, sm4_decrypt_ecb, sm4_encrypt_ecb
from .offline_trust_store import OfflineTrustStore
from .sovereign_model_fallback import SovereignModelFallbackManager
from .types import (
    AirGappedSovereigntyMetrics,
    AuditBundleRecord,
    ModelFallbackTarget,
    NetworkConnectivityModeEnum,
    OfflineCertValidationResult,
    OfflineTrustAnchor,
)


class AirGappedSovereigntyFacade:
    """Unified coordinator for air-gapped security, sovereign fallback, and GM cryptography."""

    def __init__(
        self,
        mode: NetworkConnectivityModeEnum = NetworkConnectivityModeEnum.AIR_GAPPED_ISOLATED,
        default_sovereign_target: ModelFallbackTarget | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._trust_store = OfflineTrustStore()
        self._fallback_manager = SovereignModelFallbackManager(
            initial_mode=mode,
            default_sovereign_target=default_sovereign_target,
        )
        self._archive_packer = EvidentiaryArchivePacker()
        self._metrics = AirGappedSovereigntyMetrics()

    def set_network_mode(self, mode: NetworkConnectivityModeEnum) -> None:
        """Update active network mode."""
        self._fallback_manager.set_mode(mode)

    def get_network_mode(self) -> NetworkConnectivityModeEnum:
        """Retrieve active network mode."""
        return self._fallback_manager.get_mode()

    def add_trust_anchor(self, anchor: OfflineTrustAnchor) -> None:
        """Register an offline root CA anchor."""
        self._trust_store.add_trust_anchor(anchor)

    def list_trust_anchors(self) -> list[OfflineTrustAnchor]:
        """List active offline root CA anchors."""
        return self._trust_store.list_trust_anchors()

    def import_crl(self, revoked_serials: list[str]) -> int:
        """Import revoked certificate serials list."""
        return self._trust_store.import_crl_bundle(revoked_serials)

    def validate_offline_certificate(
        self,
        cert_pem: str,
        cert_serial: str,
        issuer_ca: str,
        valid_until: float,
        current_time: float | None = None,
    ) -> OfflineCertValidationResult:
        """Validate certificate against offline root anchors and CRL."""
        result = self._trust_store.validate_certificate(
            cert_pem=cert_pem,
            cert_serial=cert_serial,
            issuer_ca=issuer_ca,
            valid_until=valid_until,
            current_time=current_time,
        )
        with self._lock:
            self._metrics.total_offline_validations += 1
            if result.is_valid:
                self._metrics.valid_certificates_count += 1
            if result.is_revoked:
                self._metrics.crl_revocation_hits += 1
        return result

    def register_fallback_target(self, target: ModelFallbackTarget) -> None:
        """Register a fallback target."""
        self._fallback_manager.register_fallback_target(target)

    def resolve_model(
        self,
        requested_model_id: str,
        is_remote_healthy: bool = True,
    ) -> tuple[ModelFallbackTarget, bool, str]:
        """Resolve effective execution model, triggering fallback if isolated or degraded."""
        target, was_fallback, explanation = self._fallback_manager.resolve_effective_target(
            requested_model_id=requested_model_id,
            is_remote_healthy=is_remote_healthy,
        )
        with self._lock:
            if was_fallback:
                self._metrics.model_fallback_events += 1
        return target, was_fallback, explanation

    def seal_audit_bundle(
        self,
        records: list[dict[str, str]],
        bundle_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> AuditBundleRecord:
        """Package audit records into an immutable SM3 sealed evidentiary bundle."""
        bundle = self._archive_packer.pack_bundle(
            records=records,
            bundle_id=bundle_id,
            metadata=metadata,
        )
        with self._lock:
            self._metrics.audit_bundles_sealed += 1
        return bundle

    def verify_audit_bundle(
        self,
        bundle: AuditBundleRecord,
        raw_records: list[dict[str, str]],
    ) -> bool:
        """Verify evidentiary bundle integrity against raw records."""
        return self._archive_packer.verify_bundle(bundle, raw_records)

    def hash_sovereign_data(self, data: bytes | str) -> str:
        """Compute SM3 cryptographic digest."""
        return sm3_hash(data)

    def encrypt_sovereign_data(self, key: bytes, plaintext: bytes) -> bytes:
        """Encrypt binary data with SM4-ECB."""
        return sm4_encrypt_ecb(key, plaintext)

    def decrypt_sovereign_data(self, key: bytes, ciphertext: bytes) -> bytes:
        """Decrypt binary data with SM4-ECB."""
        return sm4_decrypt_ecb(key, ciphertext)

    def get_metrics(self) -> AirGappedSovereigntyMetrics:
        """Retrieve snapshot of operational metrics."""
        with self._lock:
            return AirGappedSovereigntyMetrics(
                total_offline_validations=self._metrics.total_offline_validations,
                valid_certificates_count=self._metrics.valid_certificates_count,
                crl_revocation_hits=self._metrics.crl_revocation_hits,
                model_fallback_events=self._metrics.model_fallback_events,
                audit_bundles_sealed=self._metrics.audit_bundles_sealed,
            )
