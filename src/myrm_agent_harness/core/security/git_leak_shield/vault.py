"""Ephemeral In-Memory Secret Vault for zero-disk credential isolation.

[INPUT]
- Secret key-value pairs, base environment dictionaries

[OUTPUT]
- EphemeralSecretVault: In-memory credential manager with environment injection and disk-dump prevention

[POS]
Harness core security vault. Enforces the first cardinal rule of secret governance:
credentials must live exclusively in memory and be injected directly into subprocess
environments, never written to disk .env files.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_DISALLOWED_PERSISTENCE_FILENAMES: frozenset[str] = frozenset({
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.staging",
    "secrets.env",
    "credentials.env",
})


class EphemeralSecretVault:
    """Manages sensitive API credentials strictly within memory."""

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}
        self._lock = threading.Lock()

    def set_secret(self, key: str, value: str) -> None:
        """Store a sensitive credential in volatile memory."""
        with self._lock:
            self._secrets[key] = value

    def get_secret(self, key: str) -> str | None:
        """Retrieve a secret by name."""
        with self._lock:
            return self._secrets.get(key)

    def list_keys(self) -> list[str]:
        """List available secret key identifiers without revealing values."""
        with self._lock:
            return sorted(self._secrets.keys())

    def inject_env(
        self,
        base_env: dict[str, str] | None = None,
        keys: list[str] | None = None,
    ) -> dict[str, str]:
        """Produce an isolated subprocess environment containing requested credentials."""
        env = dict(base_env) if base_env is not None else {}
        with self._lock:
            target_keys = keys if keys is not None else self._secrets.keys()
            for k in target_keys:
                if k in self._secrets:
                    env[k] = self._secrets[k]
        return env

    def validate_no_disk_secret_dump(self, file_path: str, content: str) -> None:
        """Assert that sensitive credentials are not being persisted to disk files."""
        filename = Path(file_path).name.lower()
        if filename in _DISALLOWED_PERSISTENCE_FILENAMES:
            with self._lock:
                for k, v in self._secrets.items():
                    if v and v in content:
                        logger.error(
                            "Blocked attempt to persist secret '%s' to disk file: %s",
                            k,
                            file_path,
                        )
                        raise ValueError(
                            f"Security violation: Attempted to write secret credential '{k}' "
                            f"to disk file '{file_path}'. Credentials must remain strictly in memory."
                        )

    def clear(self) -> None:
        """Purge all secrets from memory."""
        with self._lock:
            self._secrets.clear()
