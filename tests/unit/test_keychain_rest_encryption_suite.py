"""
[POS] tests/unit/test_keychain_rest_encryption_suite.py
[INPUT] pytest, tmp_path, pathlib
[OUTPUT] Comprehensive unit tests for Hardware-Rooted OS Keychain & Transparent Rest Encryption Suite

Validates keychain binding, transparent rest cipher, file encryption, cold-boot guards, and instant purge.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.core.security.keychain_rest_encryption import (
    CipherEnvelope,
    ColdBootDefenseGuard,
    EncryptionDomain,
    KeychainBackendType,
    KeychainRestEncryptionSuite,
    KeychainStatus,
    KeyPurgeScope,
    NativeKeychainBinder,
    PurgeReport,
    TransparentRestCipher,
)


def test_native_keychain_binder_ephemeral_fallback() -> None:
    """Validate ephemeral fallback store when operating without platform hardware keychain."""
    binder = NativeKeychainBinder(
        service_name="test.myrm.security",
        account_name="test_account_1",
        force_backend=KeychainBackendType.FALLBACK_EPHEMERAL,
    )

    assert binder.backend_type == KeychainBackendType.FALLBACK_EPHEMERAL
    assert not binder.is_hardware_backed
    assert binder.degradation_warning is not None

    # First access generates and saves master key
    key1: bytes = binder.get_or_create_master_key()
    assert len(key1) == 32

    # Subsequent access retrieves identical key
    key2: bytes | None = binder.get_master_key()
    assert key2 == key1

    # Deletion clears key
    deleted = binder.delete_master_key()
    assert deleted
    assert binder.get_master_key() is None


def test_transparent_rest_cipher_roundtrip() -> None:
    """Validate transparent AES-256-GCM encryption and decryption with HKDF domain separation."""
    cipher = TransparentRestCipher()
    master_key = b"0" * 32  # 256-bit test key

    plaintext = "SensitiveMedicalDiagnosticNote:Patient-X-Confidential"
    envelope: CipherEnvelope = cipher.encrypt_text(
        plaintext,
        domain=EncryptionDomain.HEALTH_RECORDS,
        master_key=master_key,
    )

    assert envelope.envelope_id.startswith("env-")
    assert envelope.domain == EncryptionDomain.HEALTH_RECORDS
    assert envelope.ciphertext_hex != ""
    assert len(envelope.nonce_hex) == 24  # 12 bytes hex
    assert len(envelope.tag_hex) == 32  # 16 bytes hex

    decrypted = cipher.decrypt_text(envelope, master_key)
    assert decrypted == plaintext
    assert cipher.metrics.encryptions_total == 1
    assert cipher.metrics.decryptions_total == 1


def test_transparent_rest_cipher_tamper_defense() -> None:
    """Validate that tampered ciphertext or wrong master key fails authentication tag verification."""
    cipher = TransparentRestCipher()
    master_key = b"A" * 32
    wrong_key = b"B" * 32

    envelope: CipherEnvelope = cipher.encrypt_text(
        "ImportantFinancialLedger",
        domain=EncryptionDomain.FINANCIAL_DOCS,
        master_key=master_key,
    )

    # Decrypting with wrong master key must raise ValueError
    with pytest.raises(ValueError, match="tag mismatch or invalid key"):
        cipher.decrypt_text(envelope, wrong_key)

    # Tampering with ciphertext must raise ValueError
    tampered_hex = ("00" if envelope.ciphertext_hex[:2] != "00" else "ff") + envelope.ciphertext_hex[2:]
    tampered_envelope = CipherEnvelope(
        envelope_id=envelope.envelope_id,
        domain=envelope.domain,
        salt_hex=envelope.salt_hex,
        nonce_hex=envelope.nonce_hex,
        tag_hex=envelope.tag_hex,
        ciphertext_hex=tampered_hex,
        key_fingerprint=envelope.key_fingerprint,
        created_at=envelope.created_at,
    )

    with pytest.raises(ValueError, match="tag mismatch or invalid key"):
        cipher.decrypt_text(tampered_envelope, master_key)

    assert cipher.metrics.decryption_failures >= 2


def test_transparent_file_encryption_roundtrip(tmp_path: Path) -> None:
    """Validate reading and writing sealed encrypted files on disk."""
    cipher = TransparentRestCipher()
    master_key = b"K" * 32

    source_file = tmp_path / "journal.md"
    encrypted_file = tmp_path / "journal.md.enc"
    restored_file = tmp_path / "journal_restored.md"

    raw_content = b"# Personal Journal\nVery secret thoughts and notes."
    source_file.write_bytes(raw_content)

    envelope = cipher.encrypt_file(
        source_path=source_file,
        dest_path=encrypted_file,
        domain=EncryptionDomain.PERSONAL_JOURNAL,
        master_key=master_key,
    )
    assert encrypted_file.exists()
    assert envelope.domain == EncryptionDomain.PERSONAL_JOURNAL

    # Ensure disk file is JSON envelope, not plain text
    assert b"Very secret" not in encrypted_file.read_bytes()

    restored_bytes = cipher.decrypt_file(
        source_path=encrypted_file,
        dest_path=restored_file,
        master_key=master_key,
    )
    assert restored_bytes == raw_content
    assert restored_file.read_bytes() == raw_content


def test_cold_boot_defense_and_zeroization() -> None:
    """Validate in-memory buffer zeroization and memory retention defense."""
    guard = ColdBootDefenseGuard()
    raw_key = b"SecretKeyForMemoryTest1234567890"

    guard.retain_key("acc-1", raw_key)
    assert guard.has_key("acc-1")
    assert guard.get_key("acc-1") == raw_key

    # Purging wipes and zeroizes the key buffer
    wiped_count = guard.purge_memory()
    assert wiped_count == 1
    assert not guard.has_key("acc-1")
    assert guard.get_key("acc-1") is None


def test_facade_end_to_end_and_purge(tmp_path: Path) -> None:
    """Validate KeychainRestEncryptionSuite end-to-end integration and instant purge."""
    suite = KeychainRestEncryptionSuite(
        service_name="test.myrm.suite",
        account_name="test_suite_acc",
        force_backend=KeychainBackendType.FALLBACK_EPHEMERAL,
    )

    # Status check
    status: KeychainStatus = suite.get_status()
    assert status.backend_type == KeychainBackendType.FALLBACK_EPHEMERAL
    assert not status.is_hardware_backed

    # Self test
    self_test_res = suite.self_test()
    assert self_test_res["passed"] is True
    assert self_test_res["backend"] == KeychainBackendType.FALLBACK_EPHEMERAL.value

    # Text encryption & decryption
    secret_text = "MedicalDiagnosticRecord_2026-10-06"
    env = suite.encrypt_text(secret_text, domain=EncryptionDomain.HEALTH_RECORDS)
    restored = suite.decrypt_text(env)
    assert restored == secret_text

    # File encryption
    p_src = tmp_path / "creds.txt"
    p_enc = tmp_path / "creds.txt.enc"
    p_dec = tmp_path / "creds.txt.dec"
    p_src.write_text("API_SECRET_KEY=12345678", encoding="utf-8")

    suite.encrypt_file(p_src, p_enc, domain=EncryptionDomain.AUTH_CREDENTIALS)
    suite.decrypt_file(p_enc, p_dec)
    assert p_dec.read_text(encoding="utf-8") == "API_SECRET_KEY=12345678"

    # Instant purge
    purge_report: PurgeReport = suite.purge_credentials(scope=KeyPurgeScope.KEYCHAIN_AND_MEMORY)
    assert purge_report.keys_zeroized >= 1
    assert purge_report.keychain_deleted is True

    # Memory is cleared
    assert not suite.get_status().cached_in_memory
