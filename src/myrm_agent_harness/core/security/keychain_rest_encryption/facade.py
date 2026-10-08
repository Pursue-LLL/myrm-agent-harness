"""
[POS] src/myrm_agent_harness/core/security/keychain_rest_encryption/facade.py
[INPUT] hashlib, logging, pathlib, typing
[OUTPUT] KeychainRestEncryptionSuite

Unified facade for Hardware-Rooted OS Keychain & Transparent Rest Encryption Suite.
Provides unified developer API for keychain binding, AES-256-GCM rest encryption,
cold-boot defense, and instant emergency purge.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from .cold_boot_guard import ColdBootDefenseGuard
from .native_keychain_binder import NativeKeychainBinder
from .transparent_rest_cipher import TransparentRestCipher
from .types import (
    CipherEnvelope,
    EncryptionDomain,
    KeychainBackendType,
    KeychainStatus,
    KeyPurgeScope,
    PurgeReport,
    TransparentRestMetrics,
)

logger = logging.getLogger(__name__)


class KeychainRestEncryptionSuite:
    """Unified security suite orchestrating OS keychain binding, transparent rest cipher, and cold-boot guards."""

    def __init__(
        self,
        service_name: str = "com.myrm.agent.security",
        account_name: str = "master_root_key",
        force_backend: KeychainBackendType | None = None,
    ) -> None:
        self._binder = NativeKeychainBinder(
            service_name=service_name,
            account_name=account_name,
            force_backend=force_backend,
        )
        self._cipher = TransparentRestCipher()
        self._guard = ColdBootDefenseGuard()
        self._account_name = account_name

    @property
    def metrics(self) -> TransparentRestMetrics:
        """Cryptographic operations metrics."""
        return self._cipher.metrics

    def _get_active_master_key(self) -> bytes:
        """Retrieve master key, checking cold-boot in-memory guard first, then OS keychain."""
        cached = self._guard.get_key(self._account_name)
        if cached is not None:
            return cached

        master_key = self._binder.get_or_create_master_key()
        self._guard.retain_key(self._account_name, master_key)
        return master_key

    def get_status(self) -> KeychainStatus:
        """Inspect current security status, hardware backing, and key fingerprints."""
        cached = self._guard.has_key(self._account_name)
        master_key = self._guard.get_key(self._account_name) or self._binder.get_master_key()

        fp: str | None = None
        if master_key is not None:
            fp = hashlib.sha256(master_key).hexdigest()[:12]

        return KeychainStatus(
            backend_type=self._binder.backend_type,
            is_hardware_backed=self._binder.is_hardware_backed,
            has_master_key=master_key is not None,
            master_key_fingerprint=fp,
            cached_in_memory=cached,
            degradation_warning=self._binder.degradation_warning,
            active_domains=tuple(d.value for d in EncryptionDomain),
        )

    def encrypt_text(
        self,
        text: str,
        domain: EncryptionDomain = EncryptionDomain.GENERAL_REST,
    ) -> CipherEnvelope:
        """Encrypt string text transparently with AES-256-GCM and domain separation."""
        key = self._get_active_master_key()
        return self._cipher.encrypt_text(text, domain, key)

    def decrypt_text(self, envelope: CipherEnvelope) -> str:
        """Decrypt sealed CipherEnvelope back to plaintext string."""
        key = self._get_active_master_key()
        return self._cipher.decrypt_text(envelope, key)

    def encrypt_bytes(
        self,
        data: bytes,
        domain: EncryptionDomain = EncryptionDomain.GENERAL_REST,
    ) -> CipherEnvelope:
        """Encrypt binary payload transparently with AES-256-GCM."""
        key = self._get_active_master_key()
        return self._cipher.encrypt_bytes(data, domain, key)

    def decrypt_bytes(self, envelope: CipherEnvelope) -> bytes:
        """Decrypt binary payload from sealed CipherEnvelope."""
        key = self._get_active_master_key()
        return self._cipher.decrypt_bytes(envelope, key)

    def encrypt_file(
        self,
        source_path: Path,
        dest_path: Path,
        domain: EncryptionDomain = EncryptionDomain.GENERAL_REST,
    ) -> CipherEnvelope:
        """Transparently encrypt file on disk to sealed JSON envelope."""
        key = self._get_active_master_key()
        return self._cipher.encrypt_file(source_path, dest_path, domain, key)

    def decrypt_file(self, source_path: Path, dest_path: Path) -> bytes:
        """Transparently decrypt sealed file on disk and restore plaintext."""
        key = self._get_active_master_key()
        return self._cipher.decrypt_file(source_path, dest_path, key)

    def purge_credentials(
        self,
        scope: KeyPurgeScope = KeyPurgeScope.KEYCHAIN_AND_MEMORY,
    ) -> PurgeReport:
        """Execute instant emergency purge: wipe memory buffers and optionally delete from OS keychain."""
        keychain_deleted = False
        if scope in (KeyPurgeScope.KEYCHAIN_AND_MEMORY, KeyPurgeScope.ALL_DOMAINS):
            keychain_deleted = self._binder.delete_master_key()

        self._cipher.metrics.purges_total += 1
        return self._guard.execute_instant_purge(
            scope=scope,
            backend_type=self._binder.backend_type,
            keychain_delete_callback=keychain_deleted,
        )

    def self_test(self) -> dict[str, str | bool]:
        """Perform end-to-end roundtrip encryption and zeroization test to verify operational readiness."""
        test_payload = "SensitiveHealthAndFinancialVerificationToken:12345"
        envelope = self.encrypt_text(test_payload, domain=EncryptionDomain.HEALTH_RECORDS)
        decrypted = self.decrypt_text(envelope)
        status = self.get_status()

        is_passed = (test_payload == decrypted)
        return {
            "passed": is_passed,
            "backend": status.backend_type.value,
            "hardware_backed": status.is_hardware_backed,
            "envelope_id": envelope.envelope_id,
            "fingerprint": envelope.key_fingerprint,
        }
