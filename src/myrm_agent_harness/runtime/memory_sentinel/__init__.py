"""Deterministic Lifetime and Bounded Cache Memory Sentinel Suite.

Enforces three-dimensional bounded caches (TTL, LRU, Byte-Cap), large object
spill-to-volume dehydration, and idle session freeze-eviction pipelines.

[INPUT]
- idle_session_freezer
- memory_sentinel_types
- spill_to_volume_hydrator
- three_dimensional_bounded_cache

[OUTPUT]
- (模块级副作用与注册)

[POS]
Deterministic Lifetime and Bounded Cache Memory Sentinel Suite.
"""

from .idle_session_freezer import IdleSessionFreezer
from .memory_sentinel_types import (
    BoundedCacheStats,
    CacheEvictionPolicy,
    SessionFreezeState,
    SessionSnapshotRecord,
    SpillHandle,
)
from .spill_to_volume_hydrator import SpillToVolumeHydrator
from .three_dimensional_bounded_cache import ThreeDimensionalBoundedCache

__all__ = [
    "BoundedCacheStats",
    "CacheEvictionPolicy",
    "IdleSessionFreezer",
    "SessionFreezeState",
    "SessionSnapshotRecord",
    "SpillHandle",
    "SpillToVolumeHydrator",
    "ThreeDimensionalBoundedCache",
]
