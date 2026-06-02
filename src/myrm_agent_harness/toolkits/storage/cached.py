"""Cached Storage Provider

Transparent local-cache + remote-backend storage layer.

[INPUT]
- myrm_agent_harness.toolkits.storage.base::StorageProvider (POS: Provides FileOperationObserver.)
- pathlib::Path (filesystem paths)

[OUTPUT]
- CacheStats: cache statistics (hit rate, uploads, downloads, failures)
- CachedStorageProvider: local cache + remote storage with LRU eviction and async upload

[POS]
Performance-optimization decorator for any StorageProvider backend.
Provides transparent local caching with LRU eviction, async background upload
with configurable worker pool, automatic retry, and graceful shutdown.
Framework users wrap any StorageProvider to get high-performance file access.
"""

import asyncio
import contextlib
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.storage.base import StorageProvider

logger = logging.getLogger(__name__)

MAX_UPLOAD_WORKERS = 20
DEFAULT_UPLOAD_WORKERS = 5
UPLOAD_QUEUE_SIZE = 100
WORKER_IDLE_TIMEOUT = 30.0
DEFAULT_FLUSH_TIMEOUT = 300.0


class CacheStats:
    """Cache statistics tracker (thread-safe via external lock)."""

    def __init__(self) -> None:
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.uploads = 0
        self.downloads = 0
        self.upload_failures = 0
        self.total_read_bytes = 0
        self.total_write_bytes = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, float | int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "uploads": self.uploads,
            "downloads": self.downloads,
            "upload_failures": self.upload_failures,
            "hit_rate": self.hit_rate,
            "total_read_mb": self.total_read_bytes / (1024 * 1024),
            "total_write_mb": self.total_write_bytes / (1024 * 1024),
        }


class CachedStorageProvider:
    """Transparent local-cache layer over any StorageProvider backend.

    Usage::

        cache = CachedStorageProvider(
            backend=s3_backend,
            cache_dir=Path("/tmp/storage_cache"),
            max_cache_size_mb=1000,
        )

        data = await cache.read("workspace/data.csv", namespace="session_001")
        await cache.write("workspace/result.csv", namespace="session_001", data=result)
        local = await cache.ensure_local("workspace/data.csv", namespace="session_001")
    """

    def __init__(
        self,
        backend: "StorageProvider",
        cache_dir: Path,
        max_cache_size_mb: int = 1000,
        enable_async_upload: bool = True,
        num_upload_workers: int | None = None,
    ):
        self.backend = backend
        self.cache_dir = cache_dir
        self.max_cache_size_mb = max_cache_size_mb
        self.enable_async_upload = enable_async_upload

        if num_upload_workers is None:
            num_upload_workers = DEFAULT_UPLOAD_WORKERS
        self.num_upload_workers = max(1, min(num_upload_workers, MAX_UPLOAD_WORKERS))

        if num_upload_workers > MAX_UPLOAD_WORKERS:
            logger.warning("Requested %d workers, capped to %d for safety", num_upload_workers, MAX_UPLOAD_WORKERS)

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.stats = CacheStats()
        self._stats_lock = threading.Lock()

        self._is_shutting_down = False
        self._shutdown_lock = threading.Lock()

        self._upload_queue: asyncio.Queue[tuple[str, bytes, int]] = asyncio.Queue(maxsize=UPLOAD_QUEUE_SIZE)
        self._upload_workers: list[asyncio.Task[None]] = []

        self._failed_uploads: list[tuple[str, str, float]] = []
        self._max_failed_records = 100

        self._cache_index: dict[str, tuple[Path, int, float]] = {}

        logger.warning(
            "CachedStorageProvider initialized: cache_dir=%s, max_size=%dMB, upload_workers=%d",
            cache_dir,
            max_cache_size_mb,
            self.num_upload_workers,
        )

    def _get_cache_path(self, storage_path: str, namespace: str) -> Path:
        cache_key = f"{namespace}/{storage_path}"
        return self.cache_dir / cache_key

    async def read(self, storage_path: str, namespace: str) -> bytes:
        """Read file with transparent caching."""
        cache_path = self._get_cache_path(storage_path, namespace)

        if cache_path.exists():
            with self._stats_lock:
                self.stats.hits += 1
            logger.debug("Cache HIT: %s", storage_path)
            self._cache_index[storage_path] = (cache_path, cache_path.stat().st_size, time.time())
            return cache_path.read_bytes()

        with self._stats_lock:
            self.stats.misses += 1
        logger.debug("Cache MISS: %s, downloading...", storage_path)

        data = await self.backend.read(storage_path)
        with self._stats_lock:
            self.stats.downloads += 1
            self.stats.total_read_bytes += len(data)

        await self._write_to_cache(cache_path, data, storage_path)
        return data

    async def write(self, storage_path: str, namespace: str, data: bytes) -> None:
        """Write file with async background upload to backend."""
        cache_path = self._get_cache_path(storage_path, namespace)
        await self._write_to_cache(cache_path, data, storage_path)

        with self._stats_lock:
            self.stats.total_write_bytes += len(data)

        if self.enable_async_upload:
            with self._shutdown_lock:
                if self._is_shutting_down:
                    logger.warning("System shutting down, uploading synchronously: %s", storage_path)
                    await self.backend.write(storage_path, data)
                    with self._stats_lock:
                        self.stats.uploads += 1
                    return

            await self._upload_queue.put((storage_path, data, 0))
            self._ensure_upload_worker()
            logger.debug("Queued for upload: %s (%d bytes)", storage_path, len(data))
        else:
            await self.backend.write(storage_path, data)
            with self._stats_lock:
                self.stats.uploads += 1
            logger.debug("Uploaded: %s (%d bytes)", storage_path, len(data))

    async def ensure_local(self, storage_path: str, namespace: str) -> Path:
        """Ensure file exists in local cache, returns local path."""
        cache_path = self._get_cache_path(storage_path, namespace)
        if not cache_path.exists():
            await self.read(storage_path, namespace)
        return cache_path

    async def _write_to_cache(self, cache_path: Path, data: bytes, storage_path: str) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(data)
        self._cache_index[storage_path] = (cache_path, len(data), time.time())
        await self._evict_if_needed()

    async def _evict_if_needed(self) -> None:
        """LRU eviction when cache exceeds size limit."""
        total_size_mb = sum(size for _, size, _ in self._cache_index.values()) / (1024 * 1024)
        if total_size_mb <= self.max_cache_size_mb:
            return

        logger.warning("Cache size (%.1fMB) exceeds limit (%dMB), evicting...", total_size_mb, self.max_cache_size_mb)
        sorted_items = sorted(self._cache_index.items(), key=lambda x: x[1][2])
        target_size_mb = self.max_cache_size_mb * 0.8

        for path, (cache_path, size, _) in sorted_items:
            if total_size_mb <= target_size_mb:
                break
            if cache_path.exists():
                cache_path.unlink()
            del self._cache_index[path]
            total_size_mb -= size / (1024 * 1024)
            with self._stats_lock:
                self.stats.evictions += 1
            logger.debug("Evicted: %s", path)

        logger.warning("Eviction complete, current size: %.1fMB", total_size_mb)

    def _ensure_upload_worker(self) -> None:
        self._upload_workers = [w for w in self._upload_workers if not w.done()]
        current_count = len(self._upload_workers)
        for worker_id in range(current_count, self.num_upload_workers):
            worker = asyncio.create_task(self._upload_worker(worker_id=worker_id))
            self._upload_workers.append(worker)

    async def _upload_worker(self, worker_id: int) -> None:
        """Background upload worker with retry mechanism."""
        logger.warning("Upload worker #%d started", worker_id)
        max_retries = 3

        while True:
            try:
                storage_path, data, retry_count = await asyncio.wait_for(
                    self._upload_queue.get(),
                    timeout=WORKER_IDLE_TIMEOUT,
                )
                try:
                    await self.backend.write(storage_path, data)
                    with self._stats_lock:
                        self.stats.uploads += 1
                    logger.debug("Worker #%d uploaded: %s (%d bytes)", worker_id, storage_path, len(data))
                except Exception as e:
                    if retry_count < max_retries:
                        retry_count += 1
                        logger.warning(
                            "Worker #%d upload failed (attempt %d/%d), re-queuing: %s: %s",
                            worker_id,
                            retry_count,
                            max_retries,
                            storage_path,
                            e,
                        )
                        await self._upload_queue.put((storage_path, data, retry_count))
                    else:
                        logger.error(
                            "Worker #%d upload permanently failed after %d retries: %s: %s",
                            worker_id,
                            max_retries,
                            storage_path,
                            e,
                        )
                        self._failed_uploads.append((storage_path, str(e), time.time()))
                        if len(self._failed_uploads) > self._max_failed_records:
                            self._failed_uploads.pop(0)
                        with self._stats_lock:
                            self.stats.upload_failures += 1
                finally:
                    self._upload_queue.task_done()

            except TimeoutError:
                logger.warning("Upload worker #%d stopped (idle %.0fs)", worker_id, WORKER_IDLE_TIMEOUT)
                break
            except Exception as e:
                logger.error("Upload worker #%d error: %s", worker_id, e)
                with contextlib.suppress(ValueError):
                    self._upload_queue.task_done()

    async def flush(self, timeout: float = DEFAULT_FLUSH_TIMEOUT) -> None:
        """Wait for all pending uploads to complete."""
        if self._upload_workers:
            try:
                await asyncio.wait_for(self._upload_queue.join(), timeout=timeout)
                with self._stats_lock:
                    uploads_count = self.stats.uploads
                logger.warning("All uploads flushed (%d files uploaded)", uploads_count)
            except TimeoutError:
                pending_count = self._upload_queue.qsize()
                logger.error("Flush timeout after %.0fs, %d tasks still pending", timeout, pending_count)
                raise

    async def shutdown(self, timeout: float = 60.0, force: bool = False) -> None:
        """Graceful shutdown — drain queue, cancel workers, clean up."""
        logger.warning(
            "Shutting down CachedStorageProvider (timeout=%.0fs, force=%s, pending=%d)",
            timeout,
            force,
            self._upload_queue.qsize(),
        )

        with self._shutdown_lock:
            if self._is_shutting_down:
                logger.warning("Shutdown already in progress")
                return
            self._is_shutting_down = True

        if not force and self._upload_queue.qsize() > 0:
            try:
                await asyncio.wait_for(self._upload_queue.join(), timeout=timeout)
                logger.warning("All queued uploads completed before shutdown")
            except TimeoutError:
                pending = self._upload_queue.qsize()
                logger.error(
                    "Shutdown timeout after %.0fs, %d tasks still pending. Use force=True to skip.",
                    timeout,
                    pending,
                )
                if not force:
                    raise

        cancelled_count = 0
        for worker in self._upload_workers:
            if not worker.done():
                worker.cancel()
                cancelled_count += 1

        if cancelled_count > 0:
            logger.warning("Cancelled %d upload workers", cancelled_count)

        if self._upload_workers:
            await asyncio.gather(*self._upload_workers, return_exceptions=True)
            self._upload_workers.clear()

        if force:
            cleared = 0
            while not self._upload_queue.empty():
                try:
                    self._upload_queue.get_nowait()
                    self._upload_queue.task_done()
                    cleared += 1
                except asyncio.QueueEmpty:
                    break
            if cleared > 0:
                logger.warning("Cleared %d pending uploads (force shutdown)", cleared)

        with self._stats_lock:
            uploads_count = self.stats.uploads
            failures_count = self.stats.upload_failures

        logger.warning(
            "CachedStorageProvider shutdown complete (%d uploaded, %d failed)",
            uploads_count,
            failures_count,
        )

    def get_stats(self) -> dict[str, float | int]:
        """Return cache statistics as a dictionary."""
        return self.stats.to_dict()

    def get_failed_uploads(self) -> list[tuple[str, str, float]]:
        """Return list of failed upload records: [(path, error, timestamp), ...]."""
        return self._failed_uploads.copy()
