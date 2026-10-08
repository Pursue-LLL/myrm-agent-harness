"""
[POS] src/myrm_agent_harness/core/security/keychain_rest_encryption/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] KeychainBackendType, EncryptionDomain, KeyPurgeScope, CipherEnvelope, KeychainStatus, PurgeReport, TransparentRestMetrics

Data structures and specifications for Hardware-Rooted OS Keychain & Transparent Rest Encryption Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class KeychainBackendType(StrEnum):
    """Underlying operating system keychain or credential store backend."""

    MACOS_KEYCHAIN = "MACOS_KEYCHAIN"
    WINDOWS_CREDENTIAL_MANAGER = "WINDOWS_CREDENTIAL_MANAGER"
    LINUX_SECRETSERVICE = "LINUX_SECRETSERVICE"
    FALLBACK_EPHEMERAL = "FALLBACK_EPHEMERAL"


class EncryptionDomain(StrEnum):
    """Categorized domain for cryptographic isolation and HKDF salt separation."""

    HEALTH_RECORDS = "HEALTH_RECORDS"
    FINANCIAL_DOCS = "FINANCIAL_DOCS"
    PERSONAL_JOURNAL = "PERSONAL_JOURNAL"
    AUTH_CREDENTIALS = "AUTH_CREDENTIALS"
    GENERAL_REST = "GENERAL_REST"


class KeyPurgeScope(StrEnum):
    """Scope of credentials to be wiped during instant purge."""

    IN_MEMORY_ONLY = "IN_MEMORY_ONLY"
    KEYCHAIN_AND_MEMORY = "KEYCHAIN_AND_MEMORY"
    ALL_DOMAINS = "ALL_DOMAINS"


@dataclass(frozen=True)
class CipherEnvelope:
    """Standardized AES-256-GCM envelope for transparent rest encryption."""

    envelope_id: str
    domain: EncryptionDomain
    salt_hex: str
    nonce_hex: str
    tag_hex: str
    ciphertext_hex: str
    key_fingerprint: str
    created_at: float


@dataclass(frozen=True)
class KeychainStatus:
    """Security status of the OS keychain binding and transparent rest encryption."""

    backend_type: KeychainBackendType
    is_hardware_backed: bool
    has_master_key: bool
    master_key_fingerprint: str | None
    cached_in_memory: bool
    degradation_warning: str | None
    active_domains: tuple[str, ...]


@dataclass(frozen=True)
class PurgeReport:
    """Audit report generated after an instant purge execution."""

    purge_id: str
    scope: KeyPurgeScope
    backend_type: KeychainBackendType
    keys_zeroized: int
    keychain_deleted: bool
    timestamp: float


@dataclass
class TransparentRestMetrics:
    """Metrics tracking cryptographic operations and security lifecycle."""

    encryptions_total: int = 0
    decryptions_total: int = 0
    decryption_failures: int = 0
    purges_total: int = 0
    domain_key_derivations: int = 0
    files_encrypted_total: int = 0
    files_decrypted_total: int = 0
