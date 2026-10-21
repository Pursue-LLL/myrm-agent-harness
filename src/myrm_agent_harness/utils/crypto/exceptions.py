"""Config crypto exceptions.

[INPUT]
- (none)

[OUTPUT]
- ConfigCryptoError: Base exception for config crypto operations.
- EncryptionError: Raised when encryption fails (invalid input or key).
- DecryptionError: Raised when decryption fails (wrong key or corrupted data).

[POS]
Config crypto exceptions.
"""

from __future__ import annotations


class ConfigCryptoError(Exception):
    """Base exception for config crypto operations."""


class EncryptionError(ConfigCryptoError):
    """Raised when encryption fails (invalid input or key)."""


class DecryptionError(ConfigCryptoError):
    """Raised when decryption fails (wrong key or corrupted data)."""
