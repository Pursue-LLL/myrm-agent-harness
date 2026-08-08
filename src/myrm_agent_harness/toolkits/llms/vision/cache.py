"""Prompt-aware vision result cache.

[INPUT]
myrm_agent_harness.toolkits.llms.vision.types::VisionResult (POS: Vision toolkit SSOT types)

[OUTPUT]
build_cache_key, get_vision_cache_store, VisionCacheStore

[POS]
In-memory vision result cache keyed by content hash, mode, and task. Shared by perception engine.
"""

from __future__ import annotations

import hashlib
from threading import Lock

from .types import VisionCacheKey, VisionResult


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_cache_key(
    *,
    content_hash: str,
    mode: str,
    task: str | None,
    region: str | None = None,
) -> VisionCacheKey:
    task_hash = hash_text((task or "").strip())
    return VisionCacheKey(
        content_hash=content_hash,
        mode=mode,
        task_hash=task_hash,
        region=region,
    )


class VisionCacheStore:
    """Thread-safe in-process vision cache."""

    def __init__(self) -> None:
        self._store: dict[str, VisionResult] = {}
        self._lock = Lock()

    def get(self, key: VisionCacheKey) -> VisionResult | None:
        with self._lock:
            return self._store.get(key.digest())

    def set(self, key: VisionCacheKey, result: VisionResult) -> None:
        with self._lock:
            self._store[key.digest()] = result

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_GLOBAL_VISION_CACHE = VisionCacheStore()


def get_vision_cache_store() -> VisionCacheStore:
    return _GLOBAL_VISION_CACHE
