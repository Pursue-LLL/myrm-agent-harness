"""Two-layer embedding cache.

Layer 1: In-memory LRU cache (microsecond latency)
Layer 2: SQLite persistent cache (millisecond latency)

Reduces embedding API cost for repeated text by caching vectors locally.

[INPUT]
(no external module dependencies — stdlib only: sqlite3, hashlib, pickle, threading)

[OUTPUT]
EmbeddingCache: Two-layer (LRU + SQLite) cache for embedding vectors

[POS]
Embedding cache layer. Provides a two-tier caching mechanism (memory + SQLite) that sits
between callers and the remote embedding API to avoid redundant calls.

"""

import hashlib
import logging
import pickle
import sqlite3
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class EmbeddingCache:
    """Two-layer embedding cache with LRU + SQLite persistence."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        memory_cache_size: int = 1000,
        auto_persist_interval: int = 100,
    ):
        """Initialize two-layer cache.

        Args:
            db_path: Path to SQLite cache database
            memory_cache_size: Max entries in memory cache (LRU)
            auto_persist_interval: Auto-persist every N memory hits
        """
        self.db_path = Path(db_path)
        self.memory_cache_size = memory_cache_size
        self.auto_persist_interval = auto_persist_interval

        # Layer 1: In-memory LRU cache
        self._memory_cache: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.RLock()
        self._hits_since_persist = 0

        # Layer 2: SQLite persistent cache
        self._init_db()

        logger.info(
            "EmbeddingCache initialized: memory=%d, db=%s",
            memory_cache_size,
            self.db_path,
        )

    def _connect(self) -> sqlite3.Connection:
        """Open a hardened cache connection (WAL + busy_timeout + torn-write check)."""
        from myrm_agent_harness.utils.db.sqlite import CACHE, harden_connection_sync

        conn = sqlite3.connect(str(self.db_path))
        harden_connection_sync(conn, CACHE, db_path=self.db_path)
        return conn

    def _init_db(self) -> None:
        """Initialize SQLite database."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = self._connect()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS embeddings (
                key TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                created_at REAL NOT NULL DEFAULT (julianday('now')),
                access_count INTEGER NOT NULL DEFAULT 1
            )
        """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_embeddings_access
            ON embeddings(access_count DESC, created_at DESC)
        """
        )
        conn.commit()
        conn.close()

    async def get(self, text: str) -> list[float] | None:
        """Get embedding from cache (memory first, then SQLite).

        Args:
            text: Text to get embedding for

        Returns:
            Embedding vector or None if not found
        """
        cache_key = self._compute_key(text)

        with self._lock:
            # Layer 1: Check memory cache
            if cache_key in self._memory_cache:
                # Move to end (most recently used)
                self._memory_cache.move_to_end(cache_key)
                logger.debug("EmbeddingCache HIT (memory): %s", cache_key[:16])
                return self._memory_cache[cache_key]

        # Layer 2: Check SQLite
        import asyncio

        def _get_sqlite():
            conn = self._connect()
            cursor = conn.execute("SELECT embedding FROM embeddings WHERE key = ?", (cache_key,))
            row = cursor.fetchone()
            if row:
                embedding = pickle.loads(row[0])
                conn.execute(
                    "UPDATE embeddings SET access_count = access_count + 1 WHERE key = ?",
                    (cache_key,),
                )
                conn.commit()
            else:
                embedding = None
            conn.close()
            return embedding

        embedding = await asyncio.to_thread(_get_sqlite)

        if embedding is not None:
            # Promote to memory cache
            with self._lock:
                self._memory_cache[cache_key] = embedding
                self._evict_if_needed()

            logger.debug("EmbeddingCache HIT (SQLite): %s", cache_key[:16])
            return embedding

        logger.debug("EmbeddingCache MISS: %s", cache_key[:16])
        return None

    async def put(self, text: str, embedding: list[float]) -> None:
        """Store embedding in cache (memory + optionally SQLite).

        Args:
            text: Text key
            embedding: Embedding vector
        """
        cache_key = self._compute_key(text)

        persist_needed = False
        with self._lock:
            # Store in memory cache
            self._memory_cache[cache_key] = embedding
            self._evict_if_needed()

            self._hits_since_persist += 1

            # Auto-persist to SQLite periodically
            if self._hits_since_persist >= self.auto_persist_interval:
                persist_needed = True
                self._hits_since_persist = 0

        if persist_needed:
            import asyncio
            await asyncio.to_thread(self._persist_batch)

        logger.debug("EmbeddingCache PUT: %s", cache_key[:16])

    async def get_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Get multiple embeddings from cache.

        Args:
            texts: List of texts

        Returns:
            List of embeddings (or None for cache misses)
        """
        import asyncio
        results = [None] * len(texts)
        miss_indices = []

        # Check memory cache first (fast path)
        with self._lock:
            for i, text in enumerate(texts):
                cache_key = self._compute_key(text)
                if cache_key in self._memory_cache:
                    self._memory_cache.move_to_end(cache_key)
                    results[i] = self._memory_cache[cache_key]
                else:
                    miss_indices.append((i, cache_key))

        if not miss_indices:
            return results

        # Check SQLite for misses
        def _get_sqlite_batch():
            conn = self._connect()
            updates = []
            for idx, key in miss_indices:
                cursor = conn.execute("SELECT embedding FROM embeddings WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row:
                    results[idx] = pickle.loads(row[0])
                    updates.append((key,))
            if updates:
                conn.executemany(
                    "UPDATE embeddings SET access_count = access_count + 1 WHERE key = ?",
                    updates,
                )
                conn.commit()
            conn.close()
            return updates

        updates = await asyncio.to_thread(_get_sqlite_batch)

        # Promote hits to memory cache
        if updates:
            with self._lock:
                for idx, key in miss_indices:
                    if results[idx] is not None:
                        self._memory_cache[key] = results[idx]
                        self._evict_if_needed()

        return results

    async def put_batch(self, texts: list[str], embeddings: list[list[float]]) -> None:
        """Store multiple embeddings in cache.

        Args:
            texts: List of text keys
            embeddings: List of embedding vectors
        """
        persist_needed = False
        with self._lock:
            for text, emb in zip(texts, embeddings, strict=True):
                cache_key = self._compute_key(text)
                self._memory_cache[cache_key] = emb
                self._evict_if_needed()
                self._hits_since_persist += 1

            if self._hits_since_persist >= self.auto_persist_interval:
                persist_needed = True
                self._hits_since_persist = 0

        if persist_needed:
            import asyncio
            await asyncio.to_thread(self._persist_batch)

    def _evict_if_needed(self) -> None:
        """Evict oldest entry if cache is full (LRU)."""
        if len(self._memory_cache) > self.memory_cache_size:
            # OrderedDict.popitem(last=False) removes oldest
            oldest_key, oldest_val = self._memory_cache.popitem(last=False)
            logger.debug("EmbeddingCache EVICT: %s", oldest_key[:16])

            # Persist evicted entry to SQLite
            self._persist_single(oldest_key, oldest_val)

    def _persist_single(self, cache_key: str, embedding: list[float]) -> None:
        """Persist single embedding to SQLite."""
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO embeddings (key, embedding)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    access_count = access_count + 1
            """,
                (cache_key, pickle.dumps(embedding)),
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.warning("Failed to persist embedding: %s", e)
        finally:
            conn.close()

    def _persist_batch(self) -> None:
        """Persist all memory cache entries to SQLite (batch insert)."""
        if not self._memory_cache:
            return

        conn = self._connect()
        try:
            # Batch insert all memory entries
            entries = [(key, pickle.dumps(emb)) for key, emb in self._memory_cache.items()]

            conn.executemany(
                """
                INSERT INTO embeddings (key, embedding)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    access_count = access_count + 1
            """,
                entries,
            )
            conn.commit()
            logger.debug("Persisted %d embeddings to SQLite", len(entries))
        except sqlite3.Error as e:
            logger.warning("Failed to persist batch: %s", e)
        finally:
            conn.close()

    def _compute_key(self, text: str) -> str:
        """Compute cache key for text (SHA256 hash)."""
        return hashlib.sha256(text.encode()).hexdigest()

    def clear(self) -> None:
        """Clear memory cache (SQLite remains untouched)."""
        with self._lock:
            self._memory_cache.clear()
            self._hits_since_persist = 0
        logger.info("EmbeddingCache memory cleared")

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with memory_size, sqlite_size, hit_rate estimates
        """
        with self._lock:
            memory_size = len(self._memory_cache)

        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            conn = self._connect()
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM embeddings")
                sqlite_size = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                # Table doesn't exist yet
                sqlite_size = 0
            finally:
                conn.close()
        except sqlite3.OperationalError:
            # DB file can't be opened
            sqlite_size = 0

        return {
            "memory_size": memory_size,
            "sqlite_size": sqlite_size,
            "total_size": memory_size + sqlite_size,
            "memory_capacity": self.memory_cache_size,
        }

    def close(self) -> None:
        """Persist all memory entries and close cache."""
        with self._lock:
            self._persist_batch()
            self._memory_cache.clear()
        logger.info("EmbeddingCache closed")


# Global cache instance (can be configured by business layer)
_global_cache: EmbeddingCache | None = None
_cache_lock = threading.Lock()


def get_embedding_cache(
    db_path: Path | str = ".myrm/embeddings.db",
) -> EmbeddingCache:
    """Get or create global embedding cache instance.

    Args:
        db_path: Path to cache database (default: .myrm/embeddings.db)

    Returns:
        Global EmbeddingCache instance
    """
    global _global_cache

    with _cache_lock:
        if _global_cache is None:
            _global_cache = EmbeddingCache(db_path)
        return _global_cache


def clear_embedding_cache() -> None:
    """Clear global cache instance."""
    global _global_cache

    with _cache_lock:
        if _global_cache:
            _global_cache.close()
            _global_cache = None
