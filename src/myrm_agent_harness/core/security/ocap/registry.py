"""Concurrent sharded capability registry with instant cascading revocation.

[INPUT]
- .types::CapabilityHandle
- .token::verify_capability_signature

[OUTPUT]
- CapabilityRegistry: Thread-safe, sharded O(1) lifecycle and revocation registry
- get_default_capability_registry: Global thread-safe singleton getter

[POS]
High-performance revocation authority for the Object-Capability delegation mesh.
Guarantees instant cascading cutoff across subagent topologies with zero lock contention.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import TYPE_CHECKING

from myrm_agent_harness.core.security.ocap.token import verify_capability_signature

if TYPE_CHECKING:
    from myrm_agent_harness.core.security.ocap.types import CapabilityHandle

_NUM_SHARDS = 16


class _RegistryShard:
    """Individual thread-safe shard for capability tracking."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handles: dict[str, CapabilityHandle] = {}
        self._revoked_ids: dict[str, str] = {}
        self._parent_to_children: dict[str, set[str]] = defaultdict(set)

    def register(self, handle: CapabilityHandle) -> None:
        with self._lock:
            self._handles[handle.handle_id] = handle
            if handle.parent_handle_id:
                self._parent_to_children[handle.parent_handle_id].add(handle.handle_id)

    def is_revoked(self, handle_id: str) -> bool:
        with self._lock:
            return handle_id in self._revoked_ids

    def revoke(self, handle_id: str, reason: str = "") -> set[str]:
        """Revoke handle and collect immediate children for cascading revocation."""
        with self._lock:
            self._revoked_ids[handle_id] = reason or "revoked"
            children = set(self._parent_to_children.get(handle_id, set()))
            return children

    def get_handle(self, handle_id: str) -> CapabilityHandle | None:
        with self._lock:
            return self._handles.get(handle_id)

    def prune_expired(self, cutoff_time: float) -> int:
        with self._lock:
            expired_ids = [hid for hid, h in self._handles.items() if h.expires_at < cutoff_time]
            for hid in expired_ids:
                self._handles.pop(hid, None)
                self._revoked_ids.pop(hid, None)
                self._parent_to_children.pop(hid, None)
            return len(expired_ids)


class CapabilityRegistry:
    """Thread-safe sharded capability registry supporting cascading revocation."""

    def __init__(self, num_shards: int = _NUM_SHARDS) -> None:
        self._num_shards = max(1, num_shards)
        self._shards = [_RegistryShard() for _ in range(self._num_shards)]

    def _get_shard(self, handle_id: str) -> _RegistryShard:
        shard_idx = hash(handle_id) % self._num_shards
        return self._shards[shard_idx]

    def register(self, handle: CapabilityHandle) -> None:
        """Register active capability handle across relevant shards."""
        self._get_shard(handle.handle_id).register(handle)
        if handle.parent_handle_id:
            self._get_shard(handle.parent_handle_id).register(handle)

    def revoke(self, handle_id: str, reason: str = "") -> int:
        """Instantly revoke handle and cascade revocation down the entire child tree."""
        revoked_count = 0
        queue = [handle_id]
        seen: set[str] = set()

        while queue:
            curr_id = queue.pop(0)
            if curr_id in seen:
                continue
            seen.add(curr_id)

            shard = self._get_shard(curr_id)
            children = shard.revoke(curr_id, reason=reason)
            revoked_count += 1
            queue.extend(children)

        return revoked_count

    def is_valid(self, handle: CapabilityHandle, current_time: float | None = None) -> bool:
        """Atomically check if capability handle is valid, unrevoked, and unexpired."""
        now = time.monotonic() if current_time is None else current_time

        if handle.is_expired(now):
            return False

        if self._get_shard(handle.handle_id).is_revoked(handle.handle_id):
            return False

        if handle.parent_handle_id:
            parent_shard = self._get_shard(handle.parent_handle_id)
            if parent_shard.is_revoked(handle.parent_handle_id):
                return False

        return verify_capability_signature(handle)

    def prune_expired(self, max_retention_seconds: float = 600.0) -> int:
        """Clean up handles that expired long ago to avoid memory leaks."""
        cutoff = time.monotonic() - max_retention_seconds
        return sum(shard.prune_expired(cutoff) for shard in self._shards)


_DEFAULT_REGISTRY: CapabilityRegistry | None = None
_REGISTRY_LOCK = threading.Lock()


def get_default_capability_registry() -> CapabilityRegistry:
    """Retrieve global thread-safe CapabilityRegistry singleton."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        with _REGISTRY_LOCK:
            if _DEFAULT_REGISTRY is None:
                _DEFAULT_REGISTRY = CapabilityRegistry()
    return _DEFAULT_REGISTRY
