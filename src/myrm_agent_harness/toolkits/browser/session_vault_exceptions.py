"""Exceptions for SessionVault operations.

[INPUT]
- (none — standalone module)

[OUTPUT]
- SessionVaultError: Base exception for vault operations
- InvalidDomainError: Invalid domain name exception
- EncryptionError: Encryption failure exception
- DecryptionError: Decryption failure exception
- CorruptedSessionError: Corrupted session data exception

[POS]
Exception type definitions for SessionVault. Provides fine-grained error classification
for targeted error handling by callers.
"""


class SessionVaultError(Exception):
    """Base exception for SessionVault operations."""


class InvalidDomainError(SessionVaultError):
    """Raised when domain name is invalid or contains path traversal."""


class EncryptionError(SessionVaultError):
    """Raised when encryption fails."""


class DecryptionError(SessionVaultError):
    """Raised when decryption fails."""


class CorruptedSessionError(SessionVaultError):
    """Raised when session data is corrupted."""
