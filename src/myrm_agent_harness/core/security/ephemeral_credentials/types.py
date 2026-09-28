"""Types and data structures for ephemeral credentials.

[INPUT]
- None (foundation security types)

[OUTPUT]
- EphemeralCredential: Encapsulated credential with physical memory wipe capability.
- EphemeralCredentialSummary: Safe metadata summary without secret exposure.
- SanitizedCredentialKey: Validated environment key safe from shell injection.

[POS]
Foundational memory security models in core/security/ephemeral_credentials/.
Zero external dependencies, supports ctypes.memset zeroization.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

_VALID_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_BLOCKED_ENV_KEYS = frozenset({
    "PATH",
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "PYTHONPATH",
    "PYTHONHOME",
    "DYLD_INSERT_LIBRARIES",
    "DYLD_LIBRARY_PATH",
    "NODE_OPTIONS",
    "PERL5LIB",
    "RUBYLIB",
    "SHELL",
    "IFS",
})


def validate_credential_key(key: str) -> str:
    """Validate and sanitize a credential key name.

    Raises:
        ValueError: If the key format is invalid or attempts to poison critical env vars.
    """
    normalized = key.strip().upper()
    if not _VALID_KEY_PATTERN.match(normalized):
        raise ValueError(
            f"Invalid credential key '{key}'. Must start with a letter and contain only alphanumeric characters and underscores (max 64 chars)."
        )
    if normalized in _BLOCKED_ENV_KEYS:
        raise ValueError(
            f"Blocked credential key '{key}'. Overriding critical system environment variables is strictly forbidden."
        )
    return normalized


@dataclass
class EphemeralCredential:
    """Ephemeral in-memory credential with physical memory zeroization.

    Stores secret values in a mutable bytearray to allow physical memory clearing
    (overwriting with 0x00 bytes) upon single-use consumption or revocation,
    preventing persistent secrets in process dumps.
    """

    handle_id: str
    session_id: str
    key: str
    _material: bytearray = field(repr=False)
    created_at: float = field(default_factory=time.time)
    ttl_seconds: float = 60.0
    single_use: bool = True
    is_consumed: bool = False

    @property
    def expires_at(self) -> float:
        """Timestamp when this credential expires."""
        return self.created_at + self.ttl_seconds

    @property
    def is_expired(self) -> bool:
        """Check if credential has exceeded its TTL."""
        return time.time() > self.expires_at

    def read_secret(self) -> str:
        """Read plaintext secret.

        Raises:
            ValueError: If credential has already been wiped or is expired.
        """
        if self.is_consumed and self.single_use:
            raise ValueError(f"Credential '{self.handle_id}' has already been consumed.")
        if self.is_expired:
            raise ValueError(f"Credential '{self.handle_id}' has expired (TTL={self.ttl_seconds}s).")
        if not self._material:
            raise ValueError(f"Credential '{self.handle_id}' has been physically wiped.")
        return self._material.decode("utf-8")

    def wipe(self) -> None:
        """Physically overwrite memory buffer with zeros and clear references."""
        if self._material:
            buf_len = len(self._material)
            if buf_len > 0:
                # In-place physical memory zeroization before resizing
                self._material[:] = b"\x00" * buf_len
            self._material.clear()
        self.is_consumed = True


@dataclass(frozen=True, slots=True)
class EphemeralCredentialSummary:
    """Non-sensitive metadata view of an ephemeral credential for UI display."""

    handle_id: str
    session_id: str
    key: str
    created_at: float
    expires_at: float
    ttl_seconds: float
    single_use: bool
    is_consumed: bool
    is_expired: bool
