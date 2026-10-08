"""Cryptographic Key Vault and Derivation Engine for Root Admin & User Keys.

[INPUT]
- Key creation specs, user identifiers, tenant identifiers, and raw API key strings.

[OUTPUT]
- ApiKeyRecord metadata and high-entropy API key strings with tier prefixes.

[POS]
- Harness core security vault maintaining hashed storage and derivation mechanics.
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid

from myrm_agent_harness.core.security.dual_tier_isolation.types import (
    ApiKeyRecord,
    KeyTier,
)


def compute_key_hash(raw_key: str) -> str:
    """Compute deterministic SHA-256 hex digest of raw API key."""
    return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()


class DualTierKeyVault:
    """Stores hashed API keys and handles derivation of user scoped keys."""

    def __init__(self) -> None:
        self._keys_by_hash: dict[str, ApiKeyRecord] = {}
        self._keys_by_id: dict[str, ApiKeyRecord] = {}

    def register_root_admin_key(
        self,
        allowed_scopes: list[str] | None = None,
        custom_raw_key: str | None = None,
    ) -> tuple[str, ApiKeyRecord]:
        """Create or register a Root Admin API key for control-plane operations."""
        raw_key = custom_raw_key or f"myrm_adm_{secrets.token_urlsafe(32)}"
        key_id = f"adm-{uuid.uuid4().hex[:10]}"
        key_hash = compute_key_hash(raw_key)

        scopes = tuple(allowed_scopes or ["admin:*", "schedule:*", "health:*"])
        record = ApiKeyRecord(
            key_id=key_id,
            key_hash=key_hash,
            tier=KeyTier.ROOT_ADMIN,
            user_id=None,
            agent_id=None,
            tenant_id=None,
            allowed_scopes=scopes,
            is_revoked=False,
            created_at=time.time(),
        )

        self._keys_by_hash[key_hash] = record
        self._keys_by_id[key_id] = record
        return raw_key, record

    def derive_user_key(
        self,
        user_id: str,
        tenant_id: str | None = None,
        agent_id: str | None = None,
        allowed_scopes: list[str] | None = None,
    ) -> tuple[str, ApiKeyRecord]:
        """Derive an isolated User API key bound to a specific user and tenant context."""
        raw_key = f"myrm_usr_{secrets.token_urlsafe(32)}"
        key_id = f"usr-{uuid.uuid4().hex[:10]}"
        key_hash = compute_key_hash(raw_key)

        scopes = tuple(allowed_scopes or ["data:*", "session:*", "memory:*"])
        record = ApiKeyRecord(
            key_id=key_id,
            key_hash=key_hash,
            tier=KeyTier.DERIVED_USER,
            user_id=user_id,
            agent_id=agent_id,
            tenant_id=tenant_id or f"tenant-{user_id}",
            allowed_scopes=scopes,
            is_revoked=False,
            created_at=time.time(),
        )

        self._keys_by_hash[key_hash] = record
        self._keys_by_id[key_id] = record
        return raw_key, record

    def lookup_raw_key(self, raw_key: str) -> ApiKeyRecord | None:
        """Find key metadata by raw key string."""
        key_hash = compute_key_hash(raw_key)
        return self._keys_by_hash.get(key_hash)

    def revoke_key(self, key_id: str) -> bool:
        """Revoke an active key by key_id."""
        record = self._keys_by_id.get(key_id)
        if record is None:
            return False

        updated = ApiKeyRecord(
            key_id=record.key_id,
            key_hash=record.key_hash,
            tier=record.tier,
            user_id=record.user_id,
            agent_id=record.agent_id,
            tenant_id=record.tenant_id,
            allowed_scopes=record.allowed_scopes,
            is_revoked=True,
            created_at=record.created_at,
        )
        self._keys_by_hash[record.key_hash] = updated
        self._keys_by_id[key_id] = updated
        return True
