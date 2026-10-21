"""Pure config encryption tool using AES-256-GCM.

Provides transparent encrypt/decrypt for config values. Framework layer
provides encryption primitives; business layer decides encryption policy.

[INPUT]

[OUTPUT]
- encrypt_value: dict → base64 ciphertext
- decrypt_value: ciphertext → dict
- derive_key: secret string → 256-bit key (SHA-256)

[POS]
Pure encryption tool. No business logic (no deploy_mode, no user_id).
All methods are static (no state). Key injection via parameter.

Design principles:
- No business logic (no deploy_mode, no user_id)
- No environment variables (key injected via parameter)
- Stateless (all methods are static)
- Pure functions (same input → same output)
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os

from .exceptions import DecryptionError, EncryptionError

logger = logging.getLogger(__name__)

_NONCE_BYTES = 12


class ConfigCrypto:
    """Pure config encryption tool using AES-256-GCM.

    Provides stateless encryption/decryption methods. All configuration
    (including encryption keys) must be injected via parameters.
    """

    @staticmethod
    def encrypt_value(value: dict[str, object], key: bytes) -> str:
        """Encrypt config dict → base64 ciphertext using AES-256-GCM.

        Args:
            value: Config dictionary to encrypt
            key: 256-bit encryption key (use derive_key() to generate)

        Returns:
            Base64-encoded ciphertext string

        Raises:
            EncryptionError: If encryption fails
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            json_bytes = json.dumps(value, ensure_ascii=False).encode()
            nonce = os.urandom(_NONCE_BYTES)
            ct = AESGCM(key).encrypt(nonce, json_bytes, None)
            return base64.b64encode(nonce + ct).decode("ascii")
        except Exception as e:
            raise EncryptionError(f"Encryption failed: {e}") from e

    @staticmethod
    def decrypt_value(ciphertext: str, key: bytes) -> dict[str, object]:
        """Decrypt base64 ciphertext → config dict using AES-256-GCM.

        Args:
            ciphertext: Base64-encoded ciphertext
            key: 256-bit encryption key (same key used for encryption)

        Returns:
            Decrypted config dictionary

        Raises:
            DecryptionError: If decryption fails (wrong key or corrupted data)
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            raw = base64.b64decode(ciphertext)
            nonce, ct = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
            plaintext = AESGCM(key).decrypt(nonce, ct, None)
            return json.loads(plaintext)
        except Exception as e:
            raise DecryptionError(f"Decryption failed (wrong key or corrupted data): {e}") from e

    @staticmethod
    def derive_key(secret: str) -> bytes:
        """Derive 256-bit encryption key from secret string using SHA-256.

        Args:
            secret: Secret string (e.g., from environment variable)

        Returns:
            256-bit (32-byte) encryption key

        Note:
            SHA-256 is sufficient for system-level encryption keys (not user passwords).
            For user passwords, use PBKDF2 or Argon2 instead.
        """
        return hashlib.sha256(secret.encode()).digest()
