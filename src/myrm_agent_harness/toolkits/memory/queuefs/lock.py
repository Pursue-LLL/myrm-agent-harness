"""[POS]: src/myrm_agent_harness/toolkits/memory/queuefs/lock.py
[INPUT]: Path patterns, lock modes, owner identities, and lease lifetimes.
[OUTPUT]: PathSemanticLockManager providing fine-grained path-level lease locking and deadlock prevention.
"""

import asyncio
import fnmatch
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from .models import SemanticLockLease, SemanticLockMode


class LockAcquisitionConflictError(Exception):
    """Raised when lock acquisition fails due to concurrent lease conflicts."""


def _paths_overlap(path_a: str, path_b: str) -> bool:
    """Determine whether two virtual paths overlap (exact match, glob wildcard, or prefix hierarchy)."""
    norm_a = path_a.strip().rstrip("/")
    norm_b = path_b.strip().rstrip("/")

    if norm_a == norm_b:
        return True

    if "*" in norm_a and fnmatch.fnmatchcase(norm_b, norm_a):
        return True
    if "*" in norm_b and fnmatch.fnmatchcase(norm_a, norm_b):
        return True

    # Strip trailing /* or * for directory hierarchy check
    prefix_a = norm_a.removesuffix("/*").removesuffix("*").rstrip("/")
    prefix_b = norm_b.removesuffix("/*").removesuffix("*").rstrip("/")

    if prefix_a == prefix_b:
        return True

    return norm_a.startswith(norm_b + "/") or norm_b.startswith(norm_a + "/") or (
        bool(prefix_a and prefix_b) and (
            prefix_a.startswith(prefix_b + "/") or prefix_b.startswith(prefix_a + "/")
        )
    )


class PathSemanticLockManager:
    """Thread-safe and async-safe semantic path lock coordinator managing ephemeral leases."""

    def __init__(self, default_ttl_seconds: float = 30.0) -> None:
        self.default_ttl = default_ttl_seconds
        self._leases: dict[str, SemanticLockLease] = {}
        self._lock = asyncio.Lock()

    def cleanup_expired_leases(self, now_epoch: float | None = None) -> int:
        """Purge leases that have surpassed their expiration time."""
        current = time.time() if now_epoch is None else now_epoch
        expired_ids = [lid for lid, lease in self._leases.items() if lease.is_expired(current)]
        for lid in expired_ids:
            self._leases.pop(lid, None)
        return len(expired_ids)

    async def acquire_lock(
        self,
        path_pattern: str,
        owner: str,
        mode: SemanticLockMode = SemanticLockMode.EXCLUSIVE,
        ttl_seconds: float | None = None,
    ) -> SemanticLockLease:
        """Attempt to acquire a semantic lock over a path pattern, raising on conflict."""
        effective_ttl = self.default_ttl if ttl_seconds is None else ttl_seconds
        now = time.time()

        async with self._lock:
            self.cleanup_expired_leases(now)

            # Check conflicts against currently active unexpired leases
            for lease in self._leases.values():
                if lease.owner == owner and lease.path_pattern == path_pattern and lease.mode == mode:
                    # Idempotent re-acquisition / renewal by same owner
                    lease.expires_at_epoch = now + effective_ttl
                    return lease

                if _paths_overlap(path_pattern, lease.path_pattern) and (
                    mode == SemanticLockMode.EXCLUSIVE or lease.mode == SemanticLockMode.EXCLUSIVE
                ):
                    raise LockAcquisitionConflictError(
                        f"Path '{path_pattern}' conflicts with active lease '{lease.lock_id}' "
                        f"(pattern='{lease.path_pattern}', mode='{lease.mode}', owner='{lease.owner}')"
                    )

            # Grant new lease
            lock_id = f"sem_lock_{uuid.uuid4().hex[:12]}"
            lease = SemanticLockLease(
                lock_id=lock_id,
                path_pattern=path_pattern,
                mode=mode,
                owner=owner,
                acquired_at_epoch=now,
                expires_at_epoch=now + effective_ttl,
            )
            self._leases[lock_id] = lease
            return lease

    async def release_lock(self, lock_id: str, owner: str) -> bool:
        """Release a lease if owned by the requesting entity."""
        async with self._lock:
            lease = self._leases.get(lock_id)
            if lease is None:
                return False
            if lease.owner != owner:
                return False
            self._leases.pop(lock_id, None)
            return True

    def is_locked(self, path: str, mode: SemanticLockMode | None = None) -> bool:
        """Check whether a path is currently covered by any active lock lease."""
        now = time.time()
        for lease in self._leases.values():
            if not lease.is_expired(now) and _paths_overlap(path, lease.path_pattern) and (
                mode is None or lease.mode == mode or lease.mode == SemanticLockMode.EXCLUSIVE
            ):
                return True
        return False

    def active_locks_count(self) -> int:
        """Count currently valid unexpired leases."""
        self.cleanup_expired_leases()
        return len(self._leases)

    @asynccontextmanager
    async def lock_scope(
        self,
        path_pattern: str,
        owner: str,
        mode: SemanticLockMode = SemanticLockMode.EXCLUSIVE,
        ttl_seconds: float | None = None,
    ) -> AsyncGenerator[SemanticLockLease]:
        """Async context manager handling automatic acquisition and release."""
        lease = await self.acquire_lock(path_pattern, owner=owner, mode=mode, ttl_seconds=ttl_seconds)
        try:
            yield lease
        finally:
            await self.release_lock(lease.lock_id, owner=owner)
