"""
[POS] src/myrm_agent_harness/core/security/keychain_rest_encryption/__init__.py
[INPUT] facade, types, native_keychain_binder, transparent_rest_cipher, cold_boot_guard
[OUTPUT] Public API exports

Exports for Hardware-Rooted OS Keychain & Transparent Rest Encryption Suite.
"""

from .cold_boot_guard import ColdBootDefenseGuard
from .facade import KeychainRestEncryptionSuite
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

__all__ = [
    "CipherEnvelope",
    "ColdBootDefenseGuard",
    "EncryptionDomain",
    "KeychainBackendType",
    "KeychainRestEncryptionSuite",
    "KeychainStatus",
    "KeyPurgeScope",
    "NativeKeychainBinder",
    "PurgeReport",
    "TransparentRestCipher",
    "TransparentRestMetrics",
]
