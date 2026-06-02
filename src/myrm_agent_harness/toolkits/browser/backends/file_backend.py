"""Local filesystem backend for SessionVault.

[INPUT]
- .session_vault_exceptions::InvalidDomainError (POS: Exception type definitions for SessionVault. Provides fine-grained error classification for targeted error handling by callers.)

[OUTPUT]
- FileVaultBackend: Local filesystem backend implementation
- is_valid_domain_name: Domain name validation helper
- load_or_create_key: Key file management helper

[POS]
Local file system backend for SessionVault. Uses URL encoding for bijective
domain-to-filename mapping. Defense in depth: validates domains at backend layer.
Atomic writes via temp file + rename, preventing data corruption。
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
from pathlib import Path
from urllib.parse import quote, unquote

from ..session_vault_exceptions import InvalidDomainError

logger = logging.getLogger(__name__)

_MAX_DOMAIN_LENGTH = 255
_DOMAIN_PATTERN = re.compile(r"^(?=.*[a-zA-Z0-9])[a-zA-Z0-9._:-]+$")


def is_valid_domain_name(domain: str) -> bool:
    """Validate domain name for security (prevent path traversal).

    Whitelist validation: only allow [a-zA-Z0-9._:-] with length 1-255,
    requiring at least one alphanumeric character. This rejects path traversal
    patterns (.., /, \\, null byte) and pure-punctuation inputs (e.g., ".", ":").

    Args:
        domain: Domain name to validate (e.g., "example.com", "localhost:8080")

    Returns:
        True if domain is safe, False otherwise

    Examples:
        >>> is_valid_domain_name("example.com")
        True
        >>> is_valid_domain_name("localhost:8080")
        True
        >>> is_valid_domain_name("../../etc/passwd")
        False
        >>> is_valid_domain_name("domain/with/slash")
        False
    """
    if not domain or len(domain) > _MAX_DOMAIN_LENGTH:
        return False

    return bool(_DOMAIN_PATTERN.match(domain))


def load_or_create_key(key_path: Path) -> bytes:
    """Load a 256-bit encryption key from key_path, creating one if absent.

    The generated key file is set to mode 0600 (owner-only read/write).

    Args:
        key_path: Path to encryption key file

    Returns:
        32-byte encryption key
    """
    if key_path.exists():
        key = key_path.read_bytes()
        if len(key) == 32:
            return key
        logger.warning("Invalid key length in %s (%d bytes, expected 32), regenerating", key_path, len(key))

    key = os.urandom(32)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    with contextlib.suppress(OSError):
        key_path.chmod(0o600)
    logger.warning("Generated new session vault encryption key at %s", key_path)
    return key


class FileVaultBackend:
    """Local filesystem backend — one .enc file per domain.

    Defense-in-depth: validates domain names at backend layer to prevent
    path traversal attacks, even if upper layers fail to validate.

    Filename encoding: URL-encodes domain names to prevent collisions between
    domains with special characters (e.g., "host:8080" vs "host_8080").
    """

    def __init__(self, vault_dir: Path) -> None:
        self._dir = vault_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, domain: str) -> Path:
        """Get file path for domain using URL encoding.

        Uses URL encoding to ensure bijection between domains and filenames.
        This prevents collisions like "host:8080" vs "host_8080".

        Args:
            domain: Domain name (e.g., "example.com", "localhost:8080")

        Returns:
            Path to encrypted session file

        Raises:
            InvalidDomainError: If domain is invalid or contains path traversal
        """
        if not is_valid_domain_name(domain):
            raise InvalidDomainError(
                f"Invalid domain name: {domain!r}. Only [a-zA-Z0-9._-:] allowed, no path traversal (.., /, \\)"
            )

        safe = quote(domain, safe="")
        return self._dir / f"{safe}.enc"

    async def read(self, domain: str) -> bytes | None:
        p = self._path(domain)
        if not p.exists():
            return None
        return p.read_bytes()

    async def write(self, domain: str, data: bytes) -> None:
        """Atomic write using temp file + rename.

        Prevents data corruption during writes: write to temp file first,
        then atomically replace target file using Path.replace().

        Args:
            domain: Domain name
            data: Encrypted session bytes

        Raises:
            OSError: If write operation fails
        """
        target = self._path(domain)
        temp = target.with_suffix(".tmp")
        try:
            temp.write_bytes(data)
            temp.replace(target)
        except Exception as exc:
            if temp.exists():
                temp.unlink()
            raise OSError(f"Failed to write session for {domain}") from exc

    async def delete(self, domain: str) -> bool:
        p = self._path(domain)
        if p.exists():
            p.unlink()
            return True
        return False

    async def list_all(self) -> list[str]:
        """List all saved domains using URL decoding.

        Returns:
            List of domain names (e.g., ["example.com", "localhost:8080"])
        """
        if not self._dir.exists():
            return []

        domains = []
        for p in self._dir.glob("*.enc"):
            try:
                domains.append(unquote(p.stem))
            except Exception:
                continue

        return domains

    async def backup_corrupted(self, domain: str, data: bytes) -> None:
        """Backup corrupted session data to .corrupted file."""
        try:
            corrupted_path = self._path(domain).with_suffix(".corrupted")
            corrupted_path.write_bytes(data)
            logger.info("Backed up corrupted session to %s", corrupted_path)
        except Exception as exc:
            logger.warning("Failed to backup corrupted session: %s", exc)
