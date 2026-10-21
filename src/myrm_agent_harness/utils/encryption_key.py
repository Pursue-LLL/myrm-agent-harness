"""Encryption key resolution for local deployments.

Resolves encryption key from multiple sources with fallback chain:
1. Environment variable `CONFIG_ENCRYPTION_KEY` (Docker/SaaS/advanced users)
2. Key file at `{state_dir}/.encryption_key` (auto-generated for local mode)
3. Auto-generate and persist to key file if neither exists

[INPUT]

[OUTPUT]
- resolve_local_encryption_key: (state_dir) → bytes (256-bit key)

[POS]
Framework-layer key resolution utility. Pure file/env logic, no business policy.
Replaces device fingerprint derivation for deterministic, portable encryption.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from pathlib import Path

from myrm_agent_harness.infra.atomic_write import atomic_write

logger = logging.getLogger(__name__)

_ENV_VAR = "CONFIG_ENCRYPTION_KEY"
_KEY_FILENAME = ".encryption_key"


def resolve_local_encryption_key(state_dir: str) -> bytes:
    """Resolve 256-bit encryption key for local mode.

    Priority:
        1. CONFIG_ENCRYPTION_KEY env var (base64 or raw string)
        2. Key file at {state_dir}/.encryption_key
        3. Auto-generate → write to key file → return

    Args:
        state_dir: Data directory path (e.g., ~/.myrm)

    Returns:
        32-byte (256-bit) AES key
    """
    env_key = os.environ.get(_ENV_VAR)
    if env_key:
        logger.info("Encryption key loaded from environment variable %s", _ENV_VAR)
        return _derive_key(env_key)

    key_file = Path(state_dir).expanduser().resolve() / _KEY_FILENAME
    if key_file.is_file():
        raw = key_file.read_text(encoding="utf-8").strip()
        if raw:
            return _derive_key(raw)
        # An existing-but-empty key file signals a mid-write crash: a prior key was
        # likely lost, so re-deriving a fresh key would silently orphan data that was
        # encrypted with the old key. Warn loudly instead of silently re-keying.
        logger.warning(
            "Encryption key file %s exists but is empty; any data encrypted with the "
            "previous key can no longer be decrypted. A new key will be generated.",
            key_file,
        )

    generated = secrets.token_urlsafe(32)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write (tempfile + fsync + rename, mode=0o600) guarantees the key file is
    # never left truncated, which would otherwise trigger the empty-file path above.
    atomic_write(key_file, generated)
    logger.info("Generated new encryption key → %s", key_file)
    return _derive_key(generated)


def _derive_key(secret: str) -> bytes:
    """Derive 256-bit AES key from arbitrary secret string via SHA-256."""
    return hashlib.sha256(secret.encode("utf-8")).digest()
