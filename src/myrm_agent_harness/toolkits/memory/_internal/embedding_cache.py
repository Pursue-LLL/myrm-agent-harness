"""Two-tier embedding cache (L1: Memory LRU, L2: API).


[INPUT]

[OUTPUT]
- EmbeddingCache: Implements EmbeddingCacheProtocol for direct injection into MemoryManager

[POS]
Two-tier embedding cache. L1 uses in-memory LRU (OrderedDict + access-count eviction), L2 calls the API directly.
Supports batch deduplication, concurrency-safe (async lock), and exposes stats (hit rate, cache size).

Key design:
- Cache key: SHA256(text.strip() + model_name)
- L1 eviction: LRU with access-count cleanup
- Concurrency: async lock protects L1 and access count
- Batch optimization: deduplicate requests before API calls
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class EmbeddingCache:
    """Two-tier embedding cache implementing EmbeddingCacheProtocol."""

    def __init__(
        self,
        embedding_func: Callable[[str], Awaitable[list[float]]],
        model_name: str = "text-embedding-3-small",
        l1_max_size: int = 1000,
        batch_func: Callable[[list[str]], Awaitable[list[list[float]]]] | None = None,
    ) -> None:
        self._embed = embedding_func
        self._batch_embed = batch_func
        self._model = model_name
        self._l1_max = l1_max_size

        self._l1: OrderedDict[str, list[float]] = OrderedDict()
        self._l1_lock = asyncio.Lock()
        self._access: dict[str, int] = {}
        self._stats = {"l1_hits": 0, "l2_calls": 0, "total": 0}

    # ── EmbeddingCacheProtocol ──────────────────────────────────────

    async def get(self, text: str) -> list[float] | None:
        self._stats["total"] += 1
        key = self._key(text)

        vec = await self._l1_get(key)
        if vec is not None:
            self._stats["l1_hits"] += 1
            await self._hit(key)
            return vec

        return None

    async def put(self, text: str, embedding: list[float]) -> None:
        key = self._key(text)
        await self._l1_set(key, embedding)

    async def get_batch(self, texts: list[str]) -> list[list[float] | None]:
        return await asyncio.gather(*[self.get(t) for t in texts])

    async def put_batch(self, texts: list[str], embeddings: list[list[float]]) -> None:
        await asyncio.gather(*[self.put(t, e) for t, e in zip(texts, embeddings, strict=True)])

    # ── High-level API (used by MemoryManager) ──────────────────────

    async def get_embedding(self, text: str) -> list[float]:
        """Get or compute a single embedding (cache-through)."""
        cached = await self.get(text)
        if cached is not None:
            return cached

        vec = await self._embed(text)
        self._stats["l2_calls"] += 1
        await self.put(text, vec)
        await self._hit(self._key(text))
        return vec

    async def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """Get or compute embeddings for a batch (deduplicated, cache-through)."""
        if not texts:
            return []

        unique: list[str] = []
        idx_map: dict[str, list[int]] = {}
        for i, t in enumerate(texts):
            idx_map.setdefault(t, []).append(i)
            if len(idx_map[t]) == 1:
                unique.append(t)

        cached: dict[str, list[float]] = {}
        misses: list[str] = []

        for t in unique:
            self._stats["total"] += 1
            vec = await self.get(t)
            if vec is not None:
                cached[t] = vec
            else:
                misses.append(t)

        if misses:
            if self._batch_embed and len(misses) > 1:
                vecs = await self._batch_embed(misses)
            else:
                vecs = await asyncio.gather(*[self._embed(t) for t in misses])
            self._stats["l2_calls"] += len(misses)
            for t, v in zip(misses, vecs, strict=True):
                await self.put(t, v)
                await self._hit(self._key(t))
                cached[t] = v

        result: list[list[float]] = [[] for _ in texts]
        for t, indices in idx_map.items():
            for idx in indices:
                result[idx] = cached[t]
        return result

    # ── Monitoring ──────────────────────────────────────────────────

    def get_stats(self) -> dict[str, int | float]:
        total = self._stats["total"]
        hits = self._stats["l1_hits"]
        return {
            **self._stats,
            "hit_rate": hits / total if total else 0.0,
            "l1_size": len(self._l1),
        }

    # ── Internals ──────────────────────────────────────────────────

    def _key(self, text: str) -> str:
        h = hashlib.sha256(text.strip().encode()).hexdigest()
        return f"emb:{self._model}:{h}"

    async def _hit(self, key: str) -> None:
        async with self._l1_lock:
            self._access[key] = self._access.get(key, 0) + 1
            if len(self._access) > self._l1_max * 2:
                stale = [k for k in self._access if k not in self._l1]
                for k in stale:
                    del self._access[k]

    async def _l1_get(self, key: str) -> list[float] | None:
        async with self._l1_lock:
            if key in self._l1:
                self._l1.move_to_end(key)
                return self._l1[key]
        return None

    async def _l1_set(self, key: str, vec: list[float]) -> None:
        async with self._l1_lock:
            self._l1.pop(key, None)
            self._l1[key] = vec
            if len(self._l1) > self._l1_max:
                evicted, _ = self._l1.popitem(last=False)
                self._access.pop(evicted, None)
