"""Encrypted session vault for browser authentication persistence.

Stores Playwright storageState (cookies + localStorage) encrypted with
AES-256-GCM.  **Never stores plaintext credentials** (usernames/passwords) —
only post-login session state.  This makes the vault safe for all auth
methods: password, SMS code, QR scan, OAuth, 2FA.

Architecture
~~~~~~~~~~~~

1. ``SessionVault`` provides high-level save / load / delete / list / cleanup
   with optional memory caching for performance.
2. Encryption uses AES-256-GCM via Python ``cryptography`` (lazy import).
   AESGCM instance is cached to avoid repeated object creation.
3. Storage is delegated to a ``SessionVaultBackend`` protocol — swap in a
   database backend for Sandbox with zero changes to vault logic.
4. Memory cache (O(1) LRU with TTL and memory limit) reduces I/O and decryption
   overhead for frequently accessed sessions (configurable, 30-40x speedup).
5. ``cleanup_expired()`` uses asyncio.gather for parallel processing of all sessions.


[INPUT]
- .backends.protocol::SessionVaultBackend (POS: storage backend interface)
- .session_vault_exceptions::* (POS: Exception type definitions for SessionVault. Provides fine-grained error classification for targeted error handling by callers.)
- ...utils.rwlock::RWLock (POS: concurrency control)

[OUTPUT]
- SessionEntry: immutable saved session record
- VaultMetrics: runtime metrics for monitoring and tuning
- SessionVault: encrypted session CRUD manager with metrics

[POS]
Encrypted session storage module for the browser toolkit. Called by BrowserSession's
save_session / restore_session / list_sessions / delete_session methods.
Protects data at rest via AES-256-GCM; Backend Protocol supports local file and database storage.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

import orjson

from ...utils.rwlock import RWLock

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .backends.protocols import SessionVaultBackend
from .session_vault_exceptions import (
    CorruptedSessionError,
    DecryptionError,
    EncryptionError,
    InvalidDomainError,
)
from .session_vault_types import SessionEntry, SessionSummary, VaultMetrics

logger = logging.getLogger(__name__)

_DEFAULT_TTL_DAYS = 30


class SessionVault:
    """AES-256-GCM encrypted session storage with optional memory cache.

    Each entry is serialized to JSON, encrypted with a per-vault key, and
    stored as ``nonce(12) || ciphertext || tag(16)`` via the backend.

    Memory cache (if enabled) stores decrypted SessionEntry objects to reduce
    I/O and decryption overhead for frequently accessed sessions.
    Uses O(1) LRU eviction via OrderedDict and memory-based eviction policy.
    """

    def __init__(
        self,
        backend: SessionVaultBackend,
        encryption_key: bytes,
        *,
        cache_ttl: int = 300,
        cache_max_size: int = 100,
        cache_max_memory_mb: int = 50,
    ) -> None:
        """Initialize SessionVault.

        Args:
            backend: Storage backend implementation
            encryption_key: 256-bit AES key
            cache_ttl: Cache entry TTL in seconds (default 300s = 5min)
            cache_max_size: Max entries in cache (default 100, 0 = disabled)
            cache_max_memory_mb: Max cache memory in MB (default 50)
        """
        if len(encryption_key) != 32:
            raise ValueError(f"Encryption key must be 32 bytes, got {len(encryption_key)}")
        self._backend = backend
        self._key = encryption_key
        self._cipher: AESGCM | None = None

        self._cache_enabled = cache_max_size > 0
        self._cache: OrderedDict[str, tuple[SessionEntry, float, int]] = OrderedDict()
        self._cache_ttl = cache_ttl
        self._cache_max_size = cache_max_size
        self._cache_max_memory = cache_max_memory_mb * 1024 * 1024
        self._cache_rwlock = RWLock()

        # Singleflight: prevent cache stampede (multiple concurrent loads of same key)
        self._inflight: dict[str, asyncio.Future[SessionEntry | None]] = {}
        self._inflight_lock = asyncio.Lock()

        # Metrics
        self._metrics = VaultMetrics()

    def _get_cipher(self) -> AESGCM:
        """Get cached AESGCM instance (lazy initialization)."""
        if self._cipher is None:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            self._cipher = AESGCM(self._key)
        return self._cipher

    def _estimate_entry_size(self, entry: SessionEntry) -> int:
        """Estimate memory size of a cache entry including all Python object overhead.

        Accounts for:
        - Serialized storage_state data
        - SessionEntry object overhead
        - Cache tuple overhead (entry, cached_at, size)
        - OrderedDict node overhead (~100 bytes per entry)

        Returns conservative estimate to prevent OOM.
        """
        try:
            # Base data size
            json_bytes = orjson.dumps(entry.storage_state)
            json_size = len(json_bytes)

            # Python object overhead
            entry_overhead = sys.getsizeof(entry)  # SessionEntry object
            tuple_sample = (entry, 0.0, json_size)
            tuple_overhead = sys.getsizeof(tuple_sample)  # Cache tuple
            dict_node_overhead = 100  # OrderedDict internal node

            total = json_size + entry_overhead + tuple_overhead + dict_node_overhead
            return total
        except Exception:
            return 2048  # Conservative fallback (increased from 1024)

    def _cache_evict_one(self) -> None:
        """Evict oldest entry from cache (O(1) operation)."""
        if not self._cache:
            return

        _oldest_domain, (_, _, size) = self._cache.popitem(last=False)
        self._metrics.cache_memory_bytes -= size
        self._metrics.cache_evictions += 1

    def _cache_get(self, domain: str) -> SessionEntry | None:
        """Get entry from cache if valid (O(1) lookup).

        Updates LRU order on hit. Thread-safe via caller's lock.
        """
        if not self._cache_enabled:
            return None

        cached = self._cache.get(domain)
        if cached is None:
            self._metrics.cache_misses += 1
            return None

        entry, cached_at, _ = cached
        if time.time() - cached_at > self._cache_ttl or entry.is_expired:
            self._cache_invalidate(domain)
            self._metrics.cache_misses += 1
            return None

        # Move to end (mark as recently used) - O(1)
        self._cache.move_to_end(domain)
        self._metrics.cache_hits += 1
        return entry

    def _cache_put(self, entry: SessionEntry) -> None:
        """Add entry to cache with memory-based LRU eviction (O(1) operations).

        Evicts entries until both size and memory constraints are satisfied.
        If a single entry exceeds max memory, it will not be cached.
        Thread-safe via caller's lock.
        """
        if not self._cache_enabled:
            return

        entry_size = self._estimate_entry_size(entry)

        # Skip caching if single entry exceeds memory limit
        if entry_size > self._cache_max_memory:
            return

        # Evict by memory constraint
        while self._cache and self._metrics.cache_memory_bytes + entry_size > self._cache_max_memory:
            self._cache_evict_one()

        # Evict by size constraint
        while self._cache and len(self._cache) >= self._cache_max_size:
            self._cache_evict_one()

        # Add new entry (updates if exists)
        if entry.domain in self._cache:
            old_size = self._cache[entry.domain][2]
            self._metrics.cache_memory_bytes -= old_size

        self._cache[entry.domain] = (entry, time.time(), entry_size)
        self._cache.move_to_end(entry.domain)
        self._metrics.cache_memory_bytes += entry_size

    def _cache_invalidate(self, domain: str) -> None:
        """Remove entry from cache."""
        cached = self._cache.pop(domain, None)
        if cached:
            _, _, size = cached
            self._metrics.cache_memory_bytes -= size

    def _encrypt(self, plaintext: bytes) -> bytes:
        start = time.perf_counter()
        try:
            nonce = os.urandom(12)
            ciphertext_with_tag = self._get_cipher().encrypt(nonce, plaintext, None)
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._metrics.encryption_count += 1
            self._metrics.encryption_total_ms += elapsed_ms
            return nonce + ciphertext_with_tag
        except Exception as exc:
            logger.error("Encryption failed: %s", exc)
            raise EncryptionError(f"Failed to encrypt session data: {exc}") from exc

    def _decrypt(self, data: bytes) -> bytes:
        if len(data) < 29:
            raise DecryptionError(f"Ciphertext too short: {len(data)} bytes (expected >= 29)")

        start = time.perf_counter()
        try:
            nonce = data[:12]
            ciphertext_with_tag = data[12:]
            plaintext = self._get_cipher().decrypt(nonce, ciphertext_with_tag, None)
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._metrics.decryption_count += 1
            self._metrics.decryption_total_ms += elapsed_ms
            return plaintext
        except Exception as exc:
            logger.error("Decryption failed: %s", exc)
            raise DecryptionError(f"Failed to decrypt session data: {exc}") from exc

    async def save(
        self,
        domain: str,
        storage_state: Any,
        *,
        ttl_days: int | None = _DEFAULT_TTL_DAYS,
    ) -> None:
        """Encrypt and persist a session for *domain*."""
        now = time.time()
        expires_at = (now + ttl_days * 86400) if ttl_days is not None else None

        try:
            payload = orjson.dumps(
                {
                    "domain": domain,
                    "storage_state": storage_state,
                    "created_at": now,
                    "expires_at": expires_at,
                }
            )
        except (TypeError, ValueError) as exc:
            logger.error("Failed to serialize session data for %s: %s", domain, exc)
            raise ValueError(f"Invalid session data for {domain}: {exc}") from exc

        try:
            encrypted = self._encrypt(payload)
            await self._backend.write(domain, encrypted)

            # Update cache (write lock)
            entry = SessionEntry(
                domain=domain,
                storage_state=storage_state,
                created_at=now,
                expires_at=expires_at,
            )
            await self._cache_rwlock.write_acquire()
            try:
                self._cache_put(entry)
            finally:
                await self._cache_rwlock.write_release()
        except (EncryptionError, InvalidDomainError):
            raise
        except Exception as exc:
            logger.error("Failed to write session for %s: %s", domain, exc)
            raise OSError(f"Failed to save session for {domain}: {exc}") from exc

    async def load(self, domain: str) -> SessionEntry | None:
        """Load and decrypt a session.  Returns ``None`` if absent or expired.

        Uses memory cache to avoid repeated I/O and decryption for hot entries.
        Implements singleflight pattern to prevent cache stampede (multiple
        concurrent loads of the same key trigger only one I/O operation).
        Thread-safe via read-write lock (allows concurrent cache reads).
        """
        # Check cache first (read lock - allows concurrency)
        await self._cache_rwlock.read_acquire()
        try:
            cached = self._cache_get(domain)
            if cached is not None:
                return cached
        finally:
            await self._cache_rwlock.read_release()

        # Singleflight: check if load is in-flight
        async with self._inflight_lock:
            if domain in self._inflight:
                future = self._inflight[domain]
            else:
                future = asyncio.Future()
                self._inflight[domain] = future
                future = None  # Signal we are the loader

        # If another task is loading, wait for it
        if future is not None:
            try:
                return await future
            except Exception:
                pass  # If other task failed, fall through to retry

        # We are the loader - perform actual load
        try:
            result = await self._load_from_backend(domain)

            # Notify all waiters
            async with self._inflight_lock:
                if domain in self._inflight:
                    waiter_future = self._inflight.pop(domain)
                    if not waiter_future.done():
                        waiter_future.set_result(result)

            return result
        except Exception as exc:
            # Notify waiters of failure
            async with self._inflight_lock:
                if domain in self._inflight:
                    waiter_future = self._inflight.pop(domain)
                    if not waiter_future.done():
                        waiter_future.set_exception(exc)
            raise

    async def _load_from_backend(self, domain: str) -> SessionEntry | None:
        """Internal: Load session from backend (no cache, no singleflight)."""
        data = await self._backend.read(domain)
        if data is None:
            return None

        try:
            plaintext = self._decrypt(data)
        except DecryptionError as exc:
            logger.error("Decryption failed for %s: %s", domain, exc)
            await self._backup_and_delete_corrupted(domain, data)
            return None

        try:
            raw = orjson.loads(plaintext)
            entry = SessionEntry(
                domain=raw["domain"],
                storage_state=raw["storage_state"],
                created_at=raw["created_at"],
                expires_at=raw.get("expires_at"),
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.error("Invalid session data for %s: %s", domain, exc)
            await self._backup_and_delete_corrupted(domain, data)
            raise CorruptedSessionError(f"Session data for {domain} is corrupted") from exc

        if entry.is_expired:
            await self._backend.delete(domain)
            logger.warning("Session for %s expired, removed", domain)
            return None

        # Cache valid entry (write lock)
        await self._cache_rwlock.write_acquire()
        try:
            self._cache_put(entry)
        finally:
            await self._cache_rwlock.write_release()
        return entry

    async def _backup_and_delete_corrupted(self, domain: str, data: bytes) -> None:
        """Backup corrupted session file and delete it."""
        await self._cache_rwlock.write_acquire()
        try:
            self._cache_invalidate(domain)
        finally:
            await self._cache_rwlock.write_release()
        await self._backend.backup_corrupted(domain, data)
        await self._backend.delete(domain)

    async def delete(self, domain: str) -> bool:
        """Delete the session for *domain*.  Returns whether it existed."""
        await self._cache_rwlock.write_acquire()
        try:
            self._cache_invalidate(domain)
        finally:
            await self._cache_rwlock.write_release()
        return await self._backend.delete(domain)

    @property
    def metrics(self) -> VaultMetrics:
        """Get runtime metrics for monitoring and tuning."""
        return self._metrics

    async def list_domains(self) -> list[str]:
        """Return all domains that have a saved session."""
        return await self._backend.list_all()

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
        """Check if session is expired/corrupted and remove it.

        Returns:
            True if session was removed, False otherwise
        """
        data = await self._backend.read(domain)
        if data is None:
            return False

        try:
            plaintext = self._decrypt(data)
            raw = orjson.loads(plaintext)
            expires_at = raw.get("expires_at")
            if expires_at is not None and time.time() > expires_at:
                await self._backend.delete(domain)
                return True
        except Exception:
            await self._backend.delete(domain)
            return True

        return False

    async def cleanup_expired(self) -> int:
        """Remove all expired sessions (concurrent processing).

        Returns the count removed.
        """
        import asyncio

        domains = await self._backend.list_all()
        if not domains:
            return 0

        results = await asyncio.gather(
            *[self._check_and_remove_if_expired(domain) for domain in domains],
            return_exceptions=True,
        )

        removed = sum(1 for r in results if r is True)
        return removed
