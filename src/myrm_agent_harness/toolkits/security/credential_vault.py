"""Credential vault for storing and resolving passwords and TOTP seeds in memory.

[INPUT]
- None

[OUTPUT]
- CredentialVault: In-memory secure credential storage and resolver.

[POS]
Provides a secure in-memory vault for the execution engine (Harness) to hold
decrypted credentials. The LLM only sees the credential labels, and the
execution engine resolves the label to the actual password or TOTP token
at the moment of injection (DOM or OS level).
"""

import base64
import hashlib
import hmac
import struct
import time
from dataclasses import dataclass


@dataclass
class CredentialEntry:
    """A credential entry containing a password and/or TOTP seed."""
    label: str
    password: str | None = None
    totp_seed: str | None = None


class CredentialVault:
    """In-memory secure credential storage and resolver.
    
    This vault is populated by the Server layer (which decrypts the credentials
    from the database) and is used by the Harness layer to resolve labels
    into actual passwords or TOTP tokens during execution.
    """

    def __init__(self) -> None:
        self._credentials: dict[str, CredentialEntry] = {}

    def add_credential(self, label: str, password: str | None = None, totp_seed: str | None = None) -> None:
        """Add a credential to the in-memory vault."""
        self._credentials[label] = CredentialEntry(label=label, password=password, totp_seed=totp_seed)

    def remove_credential(self, label: str) -> None:
        """Remove a credential from the vault."""
        self._credentials.pop(label, None)

    def clear(self) -> None:
        """Clear all credentials from memory."""
        self._credentials.clear()

    def get_password(self, label: str) -> str:
        """Get the password for a given label.
        
        Raises:
            KeyError: If the label is not found.
            ValueError: If the credential does not have a password.
        """
        if label not in self._credentials:
            raise KeyError(f"Credential label '{label}' not found in vault.")

        entry = self._credentials[label]
        if not entry.password:
            raise ValueError(f"Credential '{label}' does not have a password configured.")

        return entry.password

    def get_totp_token(self, label: str) -> str:
        """Generate a 6-digit TOTP token for a given label.
        
        Raises:
            KeyError: If the label is not found.
            ValueError: If the credential does not have a TOTP seed, or if the seed is invalid.
        """
        if label not in self._credentials:
            raise KeyError(f"Credential label '{label}' not found in vault.")

        entry = self._credentials[label]
        if not entry.totp_seed:
            raise ValueError(f"Credential '{label}' does not have a TOTP seed configured.")

        try:
            # Pad the base32 string if necessary
            seed = entry.totp_seed.strip().replace(' ', '').upper()
            padding = (8 - len(seed) % 8) % 8
            seed += '=' * padding

            key = base64.b32decode(seed)
            msg = struct.pack(">Q", int(time.time() / 30))
            h = hmac.new(key, msg, hashlib.sha1).digest()
            o = h[19] & 15
            h_int = (struct.unpack(">I", h[o:o+4])[0] & 0x7fffffff) % 1000000
            return f"{h_int:06d}"
        except Exception as e:
            raise ValueError(f"Failed to generate TOTP token for '{label}': {e}") from e

    def list_labels(self) -> list[str]:
        """List all available credential labels."""
        return list(self._credentials.keys())

# Global singleton for the execution engine to use
_global_credential_vault = CredentialVault()

def get_global_credential_vault() -> CredentialVault:
    """Get the global CredentialVault instance."""
    return _global_credential_vault
