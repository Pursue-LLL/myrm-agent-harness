"""Inventory and expired-session sweep of a ``SessionVault``.

[INPUT]
- .backends.protocols::SessionVaultBackend (POS: storage backend interface)
- .exceptions::DecryptionError (POS: Exception type definitions for SessionVault. Provides fine-grained error classification for targeted error handling by callers.)
- .types::SessionSummary (POS: lightweight metadata of one saved session)

[OUTPUT]
- SessionVaultMaintenanceMixin: ``list_summaries`` and ``cleanup_expired`` for a vault that can decrypt its entries

[POS]
Everything that walks all saved sessions: the metadata listing and the sweep that deletes expired sessions
and sets unreadable ones aside. Mixed into ``SessionVault``, which supplies the backend, the cipher and the
corrupted-file backup.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

import orjson

from .exceptions import DecryptionError
from .types import SessionSummary

if TYPE_CHECKING:
    from .backends.protocols import SessionVaultBackend

logger = logging.getLogger(__name__)


class SessionVaultMaintenanceMixin:
    """Listing and sweeping of every saved session; the host vault provides the members declared below."""

    if TYPE_CHECKING:
        _backend: SessionVaultBackend

        def _decrypt(self, data: bytes) -> bytes: ...

        async def _backup_and_delete_corrupted(self, domain: str, data: bytes) -> None: ...

    async def list_summaries(self) -> list[SessionSummary]:
        """Return lightweight metadata for all saved sessions.

        Decrypts each entry to extract metadata but does NOT cache the
        full storage_state, avoiding unnecessary memory consumption.
        Corrupted or unreadable entries are silently skipped.
        """
        domains = await self._backend.list_all()
        if not domains:
            return []

        summaries: list[SessionSummary] = []
        for domain in domains:
            data = await self._backend.read(domain)
            if data is None:
                continue
            try:
                plaintext = self._decrypt(data)
                raw = orjson.loads(plaintext)
                storage_state = raw.get("storage_state", {})
                cookies = storage_state.get("cookies", [])
                origins = storage_state.get("origins", [])
                ls_count = sum(len(o.get("localStorage", [])) for o in origins)
                summary = SessionSummary(
                    domain=raw["domain"],
                    created_at=raw["created_at"],
                    expires_at=raw.get("expires_at"),
                    cookie_count=len(cookies),
                    local_storage_count=ls_count,
                )
                summaries.append(summary)
            except Exception:
                logger.warning("Failed to read session summary for %s, skipping", domain)
        return summaries

    async def _check_and_remove_if_expired(self, domain: str) -> bool:
        """Remove the session if it is expired, or set it aside if it cannot be read.

        An unreadable file is not known to be expired (a regenerated or rotated vault key makes
        every file look that way), so it goes through the same backup-then-delete path as ``load``.

        Returns:
            True if session was removed, False otherwise
        """
        data = await self._backend.read(domain)
        if data is None:
            return False

        try:
            raw = orjson.loads(self._decrypt(data))
            expired = raw.get("expires_at") is not None and time.time() > raw["expires_at"]
        except (DecryptionError, ValueError, TypeError, AttributeError) as exc:
            logger.warning("Session for %s is unreadable, setting it aside: %s", domain, exc)
            await self._backup_and_delete_corrupted(domain, data)
            return True

        if expired:
            await self._backend.delete(domain)
            return True
        return False

    async def cleanup_expired(self) -> int:
        """Remove all expired sessions (concurrent processing).

        Returns the count removed.
        """
        domains = await self._backend.list_all()
        if not domains:
            return 0

        results = await asyncio.gather(
            *[self._check_and_remove_if_expired(domain) for domain in domains],
            return_exceptions=True,
        )

        removed = sum(1 for r in results if r is True)
        return removed
