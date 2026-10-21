"""Tests for device fingerprint utility."""

import base64

from myrm_agent_harness.utils.device_fingerprint import (
    derive_key_from_fingerprint,
    generate_recovery_key,
    get_device_fingerprint,
)


def test_get_device_fingerprint():
    """Test device fingerprint generation."""
    fp1 = get_device_fingerprint()
    fp2 = get_device_fingerprint()

    assert fp1 == fp2
    assert len(fp1) == 64
    assert all(c in "0123456789abcdef" for c in fp1)


def test_generate_recovery_key():
    """Test recovery key generation."""
    key1 = generate_recovery_key()
    key2 = generate_recovery_key()

    assert key1 != key2
    assert len(key1) == 39
    assert key1.count("-") == 7

    parts = key1.split("-")
    assert len(parts) == 8
    assert all(len(part) == 4 for part in parts)


def test_derive_key_from_fingerprint():
    """Test encryption key derivation from fingerprint."""
    fp = get_device_fingerprint()
    key1 = derive_key_from_fingerprint(fp)
    key2 = derive_key_from_fingerprint(fp)

    assert key1 == key2
    assert len(key1) == 32

    key3 = derive_key_from_fingerprint(fp, salt="different-salt")
    assert key3 != key1


def test_encryption_with_derived_key():
    """Test that derived key can be used for encryption/decryption."""
    from myrm_agent_harness.utils.crypto import ConfigCrypto

    fp = get_device_fingerprint()
    key = derive_key_from_fingerprint(fp)

    test_data = {"api_key": "secret-key-123", "endpoint": "https://api.example.com"}

    ciphertext = ConfigCrypto.encrypt_value(test_data, key)
    assert isinstance(ciphertext, str)
    assert len(ciphertext) > 0

    decrypted = ConfigCrypto.decrypt_value(ciphertext, key)
    assert decrypted == test_data


def test_recovery_key_format():
    """Test recovery key has correct format for user display."""
    key = generate_recovery_key()

    raw_base32 = key.replace("-", "")
    assert len(raw_base32) == 32

    decoded = base64.b32decode(raw_base32)
    assert len(decoded) == 20
