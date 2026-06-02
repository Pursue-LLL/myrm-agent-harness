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
import stat
from pathlib import Path

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
    if key_file.exists():
        raw = key_file.read_text(encoding="utf-8").strip()
        if raw:
            return _derive_key(raw)

    generated = secrets.token_urlsafe(32)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(generated, encoding="utf-8")
    key_file.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    logger.info("Generated new encryption key → %s", key_file)
    return _derive_key(generated)


def _derive_key(secret: str) -> bytes:
    """Derive 256-bit AES key from arbitrary secret string via SHA-256."""
    return hashlib.sha256(secret.encode("utf-8")).digest()
