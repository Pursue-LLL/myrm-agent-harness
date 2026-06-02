"""Domain-level learning metrics manager.

Responsibilities:
- Unified management of all domain learning metrics (web_fetch + browser)
- Provides domain-level cost learning, failure decay, and wait strategy data
- JSON serialization persistence (with file lock support)

Architecture:
- Framework layer adapts to deployment scenarios via parameter injection
- Local deployment: ~/.myrm/domain_metrics.json
- Per-user cloud sandbox: /workspace/.myrm/domain_metrics.json
- Per-task cloud sandbox: /tmp/domain_metrics.json (isolated) or /mnt/shared/ (shared)

[INPUT]
- infra.delivery.storage_metrics::MonitoredStorageCallback (POS: StorageProvider)
- toolkits.storage.base::StorageProvider (POS: Storage provider abstract base class. Defines the unified storage interface contract for all storage backends. Supports file read/write, delete, list, info query, and namespace isolation. Method names use read/write (not get/put), fully compatible with the StorageBackend Protocol.)

[OUTPUT]
- DomainMetricsManager: Domain-level learning metrics manager.
- get_global_domain_metrics_manager: Get the global domain metrics manager (singleton).

[POS]
Domain-level learning metrics manager.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.utils import os_compat as fcntl

from ..fetchers.protocols import FetcherType
from .models import DomainMetrics

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.storage.base import StorageProvider

logger = logging.getLogger(__name__)

_global_domain_metrics_manager: DomainMetricsManager | None = None


def get_global_domain_metrics_manager() -> DomainMetricsManager:
    """Get the global domain metrics manager (singleton)."""
    global _global_domain_metrics_manager
    if _global_domain_metrics_manager is None:
        _global_domain_metrics_manager = DomainMetricsManager()
    return _global_domain_metrics_manager


class DomainMetricsManager:
    """Domain-level learning metrics manager.

    Core capabilities:
    - Domain-level metric storage and retrieval
    - Async background persistence (reuses AdaptiveRouter async save mechanism)
    - StorageProvider support (cloud storage S3/R2/GCS)
    - File lock support (local filesystem multi-process scenarios)
    - Auto-cleanup of expired domains (7 days inactive)

    Two storage modes:
    1. StorageProvider mode: abstract interface, supports cloud storage (S3/R2/GCS)
    2. Local file mode: direct Path operations, with file lock (fcntl)

    Note: StorageProvider mode does not load data in __init__ (async lazy load);
          local file mode loads synchronously in __init__.

    Concurrency model:
    - Read-write lock protects in-memory data structures
    - File lock protects local JSON file (multi-process scenarios)
    """

    def __init__(
        self,
        *,
        storage_path: str | Path | None = None,
        storage_provider: StorageProvider | None = None,
        storage_key: str = "web_fetch/domain_metrics.json",
        use_file_lock: bool = False,
        max_domains: int = 10000,
        save_interval_minutes: int = 5,
        inactive_days: int = 7,
    ):
        """Initialize domain metrics manager.

        Args:
            storage_path: Storage file path (local mode, None uses default path)
            storage_provider: Storage provider (cloud storage mode, optional)
            storage_key: Storage key (StorageProvider mode, default: "web_fetch/domain_metrics.json")
            use_file_lock: Whether to enable file lock (local mode, multi-process scenarios)
            max_domains: Maximum domain count (LRU eviction)
            save_interval_minutes: Auto-save interval (minutes)
            inactive_days: Inactive domain cleanup threshold (days)
        """
        self._storage_path = self._resolve_storage_path(storage_path) if not storage_provider else None
        self._storage_provider = storage_provider
        self._storage_key = storage_key
        self._use_file_lock = use_file_lock
        self._max_domains = max_domains
        self._save_interval_minutes = save_interval_minutes
        self._inactive_days = inactive_days

        self._lock = threading.RLock()
        self._metrics: dict[str, DomainMetrics] = {}

        self._save_pending = False
        self._saver_task: asyncio.Task[None] | None = None
        self._shutdown_event = threading.Event()
        self._last_save_time = time.time()

        # Local file mode: synchronous load
        # StorageProvider mode: deferred async load (cache nature)
        if self._storage_path:
            self._load_metrics()

        logger.info(
            f"DomainMetricsManager initialized: {len(self._metrics)} domains, "
            f"file_lock={self._use_file_lock}, "
            f"storage={'StorageProvider' if self._storage_provider else str(self._storage_path)}"
        )

    @staticmethod
    def _resolve_storage_path(path: str | Path | None) -> Path:
        """Resolve storage path.

        Path selection priority:
        1. Explicit path parameter
        2. Cloud sandbox: /workspace/.myrm/
        3. Local: ~/.myrm/
        """
        if path is not None:
            return Path(path)

        if os.path.exists("/workspace/"):
            return Path("/workspace/.myrm/domain_metrics.json")

        return Path.home() / ".myrm" / "domain_metrics.json"

    def _load_metrics(self) -> None:
        """Load domain metrics from JSON file (local file mode).

        Uses fcntl file lock (synchronous), for multi-process concurrent scenarios.
        """
        assert self._storage_path is not None

        if not self._storage_path.exists():
            logger.info(f"Metrics file not found, starting fresh: {self._storage_path}")
            return

        try:
            with open(self._storage_path, encoding="utf-8") as f:
                if self._use_file_lock:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH)

                try:
                    data = json.load(f)
                    loaded_metrics = {
                        domain: DomainMetrics.from_dict(metrics_data) for domain, metrics_data in data.items()
                    }
                finally:
                    if self._use_file_lock:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            self._metrics = loaded_metrics
            logger.info(f"Loaded {len(self._metrics)} domain metrics from {self._storage_path}")

        except Exception:
            logger.error(f"Failed to load metrics from {self._storage_path}", exc_info=True)
            self._metrics = {}

    async def load_metrics_async(self) -> None:
        """Async-load domain metrics (StorageProvider mode)."""
        if not self._storage_provider:
            raise RuntimeError("load_metrics_async requires StorageProvider mode")

        from myrm_agent_harness.infra.delivery.storage_metrics import (
            MonitoredStorageCallback,
            get_global_storage_metrics,
        )
        from myrm_agent_harness.infra.delivery.storage_resilience import resilient_storage_operation

        async def _load() -> dict[str, DomainMetrics]:
            data_bytes = await self._storage_provider.read(self._storage_key)
            data = json.loads(data_bytes.decode("utf-8"))
            return {domain: DomainMetrics.from_dict(metrics_data) for domain, metrics_data in data.items()}

        callback = MonitoredStorageCallback(get_global_storage_metrics())
        try:
            loaded_metrics = await resilient_storage_operation("read", _load, max_retries=2, callback=callback)

            with self._lock:
                self._metrics = loaded_metrics

            logger.info(f"Loaded {len(self._metrics)} domain metrics from StorageProvider")

        except FileNotFoundError:
            logger.info(f"Metrics not found in StorageProvider, starting fresh: {self._storage_key}")
        except Exception:
            logger.error(
                f"Failed to load metrics from StorageProvider after retries: {self._storage_key}", exc_info=True
            )

    def _save_metrics(self) -> None:
        """Save domain metrics to JSON file (local file mode, snapshot copy avoids data races)."""
        assert self._storage_path is not None

        try:
            from myrm_agent_harness.infra.atomic_write import atomic_write

            with self._lock:
                snapshot = {domain: metrics.to_dict() for domain, metrics in self._metrics.items()}

            atomic_write(self._storage_path, json.dumps(snapshot, indent=2))
            logger.info(f"Saved {len(snapshot)} domain metrics to {self._storage_path}")

        except Exception:
            logger.error(f"Failed to save metrics to {self._storage_path}", exc_info=True)

    async def _save_metrics_async(self) -> None:
        """Async-save domain metrics to StorageProvider."""
        assert self._storage_provider is not None

        from myrm_agent_harness.infra.delivery.storage_metrics import (
            MonitoredStorageCallback,
            get_global_storage_metrics,
        )
        from myrm_agent_harness.infra.delivery.storage_resilience import resilient_storage_operation

        with self._lock:
            snapshot = {domain: metrics.to_dict() for domain, metrics in self._metrics.items()}

        async def _write() -> None:
            data_bytes = json.dumps(snapshot, indent=2).encode("utf-8")
            await self._storage_provider.write(self._storage_key, data_bytes)

        callback = MonitoredStorageCallback(get_global_storage_metrics())
        try:
            await resilient_storage_operation("write", _write, max_retries=3, callback=callback)
            logger.info(f"Saved {len(snapshot)} domain metrics to StorageProvider")
        except Exception:
            logger.error(f"Failed to save metrics to StorageProvider after retries: {self._storage_key}", exc_info=True)

    def get_or_create(self, domain: str) -> DomainMetrics:
        """Get or create domain metrics (thread-safe)."""
        with self._lock:
            if domain not in self._metrics:
                self._metrics[domain] = DomainMetrics(domain=domain)

                if len(self._metrics) > self._max_domains:
                    self._evict_lru()

            return self._metrics[domain]

    def get(self, domain: str) -> DomainMetrics | None:
        """Get domain metrics (read-only, thread-safe)."""
        with self._lock:
            return self._metrics.get(domain)

    def _evict_lru(self) -> None:
        """Evict the least recently accessed domain (LRU)."""
        if not self._metrics:
            return

        lru_domain = min(self._metrics.items(), key=lambda x: x[1].last_access)[0]
        del self._metrics[lru_domain]
        logger.info(f"Evicted LRU domain: {lru_domain}")

    def request_save(self) -> None:
        """Request async save."""
        self._save_pending = True
        if self._saver_task is None or self._saver_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._saver_task = loop.create_task(self._background_saver())
            except RuntimeError:
                # No event loop: synchronous save (local file mode only)
                if self._storage_path:
                    self._save_metrics()
                # StorageProvider mode cannot save synchronously, skip

    async def _background_saver(self) -> None:
        """Background save task."""
        while not self._shutdown_event.is_set():
            await asyncio.sleep(1.0)
            if self._save_pending:
                self._save_pending = False
                if self._storage_provider:
                    await self._save_metrics_async()
                else:
                    await asyncio.to_thread(self._save_metrics)

    def maybe_periodic_save(self) -> None:
        """Periodic save check (called by AdaptiveRouter)."""
        now = time.time()
        if now - self._last_save_time > self._save_interval_minutes * 60:
            self.request_save()
            self._last_save_time = now

    def cleanup_inactive_domains(self) -> None:
        """Clean up long-inactive domains."""
        now = time.time()
        cutoff = now - self._inactive_days * 86400

        with self._lock:
            inactive = [domain for domain, metrics in self._metrics.items() if metrics.last_access < cutoff]

            for domain in inactive:
                del self._metrics[domain]

            if inactive:
                logger.info(f"Cleaned up {len(inactive)} inactive domains")

    def shutdown(self) -> None:
        """Save state on close (synchronous, reliable only for local file mode)."""
        self._shutdown_event.set()

        # Local file mode: synchronous save
        if self._storage_path:
            self._save_metrics()
        # StorageProvider mode: cannot save synchronously, relies on background task

    async def shutdown_async(self) -> None:
        """Async close and save state (recommended for StorageProvider mode)."""
        self._shutdown_event.set()
        if self._saver_task and not self._saver_task.done():
            await self._saver_task

        # Final save
        if self._storage_provider:
            await self._save_metrics_async()
        else:
            await asyncio.to_thread(self._save_metrics)

    def get_stats(self) -> dict[str, object]:
        """Get aggregate statistics."""
        with self._lock:
            if not self._metrics:
                return {
                    "total_domains": 0,
                    "storage_path": str(self._storage_path),
                    "use_file_lock": self._use_file_lock,
                }

            success_rates = []
            latencies = []
            smart_adjustments = 0
            smart_skips = 0
            total_memory_kb = 0

            per_fetcher_stats: dict[str, dict[str, float | int]] = {}
            for ft in FetcherType:
                per_fetcher_stats[ft.name] = {
                    "total_requests": 0,
                    "success_requests": 0,
                    "success_rate": 0.0,
                    "avg_success_latency_ms": 0.0,
                }

            for _domain, metrics in self._metrics.items():
                for ft in FetcherType:
                    rate = metrics.get_success_rate(ft)
                    if rate != 0.8:
                        success_rates.append(rate)

                    avg_latency = metrics.get_average_latency(ft)
                    if avg_latency:
                        latencies.append(avg_latency)

                    per_fetcher_stats[ft.name]["total_requests"] += metrics.fetcher_total_counts[ft]
                    per_fetcher_stats[ft.name]["success_requests"] += metrics.fetcher_success_counts[ft]

                timeout = metrics.get_smart_fast_timeout()
                if timeout is not None:
                    smart_adjustments += 1
                elif (metrics.networkidle_success_count + metrics.networkidle_fail_count) >= 20:
                    smart_skips += 1

                domain_size = (
                    sum(len(dq) for dq in metrics.fetcher_latencies.values())
                    + sum(len(dq) for dq in metrics.fetcher_success_latencies.values())
                    + sum(len(dq) for dq in metrics.wait_strategy_latencies.values())
                    + sum(len(dq) for dq in metrics.failure_timestamps.values())
                ) * 8
                total_memory_kb += domain_size / 1024

            for ft in FetcherType:
                total = per_fetcher_stats[ft.name]["total_requests"]
                success = per_fetcher_stats[ft.name]["success_requests"]
                if total > 0:
                    per_fetcher_stats[ft.name]["success_rate"] = success / total

                all_success_latencies = []
                for metrics in self._metrics.values():
                    success_lats = metrics.fetcher_success_latencies.get(ft)
                    if success_lats:
                        all_success_latencies.extend(success_lats)

                if all_success_latencies:
                    per_fetcher_stats[ft.name]["avg_success_latency_ms"] = sum(all_success_latencies) / len(
                        all_success_latencies
                    )

            success_rates_sorted = sorted(success_rates) if success_rates else []
            latencies_sorted = sorted(latencies) if latencies else []

            return {
                "total_domains": len(self._metrics),
                "storage_path": str(self._storage_path),
                "use_file_lock": self._use_file_lock,
                "success_rate_p50": success_rates_sorted[len(success_rates_sorted) // 2]
                if success_rates_sorted
                else None,
                "success_rate_p90": success_rates_sorted[int(len(success_rates_sorted) * 0.9)]
                if success_rates_sorted
                else None,
                "latency_p50_ms": latencies_sorted[len(latencies_sorted) // 2] if latencies_sorted else None,
                "latency_p90_ms": latencies_sorted[int(len(latencies_sorted) * 0.9)] if latencies_sorted else None,
                "smart_adjustments": smart_adjustments,
                "smart_skips": smart_skips,
                "total_memory_kb": int(total_memory_kb),
                "top_domains": sorted(
                    [(d, m.total_accesses) for d, m in self._metrics.items()],
                    key=lambda x: x[1],
                    reverse=True,
                )[:10],
                "per_fetcher": per_fetcher_stats,
            }

    def reset_domain(self, domain: str) -> bool:
        """Reset domain learning data (for correcting erroneous learning).

        Returns:
            bool: Whether the domain existed and was reset
        """
        with self._lock:
            if domain in self._metrics:
                del self._metrics[domain]
                logger.info(f"Reset domain metrics: {domain}")
                self.request_save()
                return True
            return False

    def export_metrics(self, path: str | Path) -> None:
        """Export domain metrics to a specified path (for backup and migration)."""
        export_path = Path(path)
        with self._lock:
            snapshot = {domain: metrics.to_dict() for domain, metrics in self._metrics.items()}

        export_path.parent.mkdir(parents=True, exist_ok=True)
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
        os.chmod(export_path, 0o600)
        logger.info(f"Exported {len(snapshot)} domain metrics to {export_path}")

    def import_metrics(self, path: str | Path, merge: bool = True) -> int:
        """Import domain metrics from a specified path.

        Args:
            path: Import file path
            merge: True=merge into existing data, False=replace existing data

        Returns:
            int: Number of domains imported
        """
        import_path = Path(path)
        if not import_path.exists():
            logger.error(f"Import file not found: {import_path}")
            return 0

        with open(import_path, encoding="utf-8") as f:
            data = json.load(f)
            imported_metrics = {domain: DomainMetrics.from_dict(metrics_data) for domain, metrics_data in data.items()}

        with self._lock:
            if merge:
                for domain, metrics in imported_metrics.items():
                    if domain not in self._metrics or metrics.last_access > self._metrics[domain].last_access:
                        self._metrics[domain] = metrics
            else:
                self._metrics = imported_metrics

        count = len(imported_metrics)
        logger.info(f"Imported {count} domain metrics from {import_path} (merge={merge})")
        self.request_save()
        return count

    def clear_all(self) -> int:
        """Clear all domain learning data (full reset).

        Returns:
            int: Number of domains cleared
        """
        with self._lock:
            count = len(self._metrics)
            self._metrics.clear()
            self.request_save()

        logger.info(f"Cleared all domain metrics: {count} domains")
        return count
