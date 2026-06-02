"""Persistence management module

Responsibilities:
- JSON serialization/deserialization of persistent rules
- Async background save (non-blocking decision path, snapshot avoids data races)
- Persistent rule heap reconstruction (build LRU heap after loading)
- File lock support (cloud sandbox multi-agent process concurrency)
- StorageProvidersupport (cloud-native storage)

[INPUT]
- infra.delivery.storage_metrics::MonitoredStorageCallback (POS: StorageProvider)
- toolkits.storage.base::StorageProvider (POS: Storage provider abstract base class. Defines the unified storage interface contract for all storage backends. Supports file read/write, delete, list, info query, and namespace isolation. Method names use read/write (not get/put), fully compatible with the StorageBackend Protocol.)

[OUTPUT]
- PersistenceManager: Persistence manager

[POS]
Persistence management module
"""

from __future__ import annotations

import asyncio
import heapq
import json
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.utils import os_compat as fcntl

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.storage.base import StorageProvider

import contextlib

from ..fetchers.protocols import FetcherType
from .models import HeapEntry, PersistentRule

logger = logging.getLogger(__name__)


class PersistenceManager:
    """Persistence manager

    core能力：
    - JSONSerialize（可读、可调试、跨语言compatible）
    - Async background save（ not blocking决策Path）
    - StorageProviderSupport（CloudStorageS3/R2/GCS）
    - File锁Support（LocalFile系统多进程Scenario）

    两种StorageMode：
    1. StorageProviderMode： using AbstractInterface，SupportCloudStorage（S3/R2/GCS）
    2. LocalFileMode： directly 操作Path，SupportFile锁（fcntl）

    Note: File lock只 in LocalMode可用，CloudStorageModedepends onStorageService 一致性 guarantee 。

    Args:
        rules_file: RuleFilePath（LocalMode）
        storage_provider: Storageprovides器（CloudStorageMode，optional）
        storage_key: Storage key（StorageProviderMode，Default："web_fetch/router_rules.json"）
        use_file_lock: Whether using File锁（LocalMode，Default：False）
    """

    def __init__(
        self,
        rules_file: Path | None = None,
        storage_provider: StorageProvider | None = None,
        storage_key: str = "web_fetch/router_rules.json",
        use_file_lock: bool = False,
    ):
        if storage_provider is None and rules_file is None:
            raise ValueError("Either rules_file or storage_provider must be provided")

        self._rules_file = rules_file
        self._storage_provider = storage_provider
        self._storage_key = storage_key
        self._use_file_lock = use_file_lock
        self._save_pending = False
        self._saver_task: asyncio.Task[None] | None = None
        self._shutdown_event = threading.Event()

    async def load_rules_async(
        self,
    ) -> tuple[dict[str, PersistentRule], dict[str, FetcherType], list[HeapEntry]]:
        """AsyncLoad持久Rule（SupportStorageProvider and LocalFile）

        Returns:
            (persistent_rules, wildcard_rules, persistent_heap)
        """
        if self._storage_provider:
            return await self._load_from_storage()
        elif self._rules_file:
            return await asyncio.to_thread(self._load_from_file)
        else:
            return {}, {}, []

    def load_rules(
        self,
    ) -> tuple[dict[str, PersistentRule], dict[str, FetcherType], list[HeapEntry]]:
        """SyncLoad持久Rule（向后compatible，OnlySupportLocalFileMode）

        Returns:
            (persistent_rules, wildcard_rules, persistent_heap)
        """
        if self._storage_provider:
            raise RuntimeError("StorageProvider mode requires async load_rules_async()")

        if not self._rules_file:
            return {}, {}, []

        return self._load_from_file()

    def _load_from_file(
        self,
    ) -> tuple[dict[str, PersistentRule], dict[str, FetcherType], list[HeapEntry]]:
        """from LocalFileLoadRule

        Returns:
            (persistent_rules, wildcard_rules, persistent_heap)
        """
        assert self._rules_file is not None

        if not self._rules_file.exists():
            logger.warning(f"Rules file not found, starting with empty rules: {self._rules_file}")
            return {}, {}, []

        try:
            with open(self._rules_file, encoding="utf-8") as f:
                if self._use_file_lock:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH)

                try:
                    data = json.load(f)
                    raw_rules = data.get("exact", {})

                    persistent_rules: dict[str, PersistentRule] = {}
                    for domain, rule_data in raw_rules.items():
                        if isinstance(rule_data, dict):
                            persistent_rules[domain] = PersistentRule.from_dict(rule_data)
                        else:
                            raise ValueError(f"Invalid rule data format for domain {domain}: {rule_data}")

                    wildcard_rules_data = data.get("wildcard", {})
                    wildcard_rules = {
                        domain: FetcherType[ft] if isinstance(ft, str) else ft
                        for domain, ft in wildcard_rules_data.items()
                    }
                finally:
                    if self._use_file_lock:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            persistent_heap = [HeapEntry(rule.last_access_time, domain) for domain, rule in persistent_rules.items()]
            heapq.heapify(persistent_heap)

            logger.info(f"Loaded {len(persistent_rules)} exact rules, {len(wildcard_rules)} wildcard rules")
            return persistent_rules, wildcard_rules, persistent_heap

        except Exception:
            logger.error(f"Failed to load rules from {self._rules_file}", exc_info=True)
            return {}, {}, []

    async def _load_from_storage(
        self,
    ) -> tuple[dict[str, PersistentRule], dict[str, FetcherType], list[HeapEntry]]:
        """from StorageProviderLoadRule

        Returns:
            (persistent_rules, wildcard_rules, persistent_heap)
        """
        assert self._storage_provider is not None

        from myrm_agent_harness.infra.delivery.storage_metrics import (
            MonitoredStorageCallback,
            get_global_storage_metrics,
        )
        from myrm_agent_harness.infra.delivery.storage_resilience import resilient_storage_operation

        async def _load() -> tuple[dict[str, PersistentRule], dict[str, FetcherType], list[HeapEntry]]:
            content = await self._storage_provider.read_text(self._storage_key)
            data = json.loads(content)

            raw_rules = data.get("exact", {})
            persistent_rules: dict[str, PersistentRule] = {}
            for domain, rule_data in raw_rules.items():
                if isinstance(rule_data, dict):
                    persistent_rules[domain] = PersistentRule.from_dict(rule_data)
                else:
                    # 向后compatible
                    persistent_rules[domain] = PersistentRule(
                        fetcher_type=FetcherType[rule_data] if isinstance(rule_data, str) else rule_data,
                        last_access_time=time.time(),
                    )

            wildcard_rules_data = data.get("wildcard", {})
            wildcard_rules = {
                domain: FetcherType[ft] if isinstance(ft, str) else ft for domain, ft in wildcard_rules_data.items()
            }

            persistent_heap = [HeapEntry(rule.last_access_time, domain) for domain, rule in persistent_rules.items()]
            heapq.heapify(persistent_heap)

            logger.warning(
                f"Loaded {len(persistent_rules)} exact rules, {len(wildcard_rules)} wildcard rules from storage"
            )
            return persistent_rules, wildcard_rules, persistent_heap

        callback = MonitoredStorageCallback(get_global_storage_metrics())
        try:
            return await resilient_storage_operation("read", _load, max_retries=2, callback=callback)
        except FileNotFoundError:
            logger.warning(f"Rules not found in storage, starting with empty rules: {self._storage_key}")
            return {}, {}, []
        except Exception:
            logger.error(f"Failed to load rules from storage after retries: {self._storage_key}", exc_info=True)
            return {}, {}, []

    async def save_rules_async(
        self, persistent_rules: dict[str, PersistentRule], wildcard_rules: dict[str, FetcherType]
    ) -> None:
        """AsyncSave持久Rule（SupportStorageProvider and LocalFile）"""
        if self._storage_provider:
            await self._save_to_storage(persistent_rules, wildcard_rules)
        elif self._rules_file:
            await asyncio.to_thread(self._save_to_file, persistent_rules, wildcard_rules)

    def save_rules(self, persistent_rules: dict[str, PersistentRule], wildcard_rules: dict[str, FetcherType]) -> None:
        """SyncSave持久Rule（向后compatible，OnlySupportLocalFileMode）"""
        if self._storage_provider:
            raise RuntimeError("StorageProvider mode requires async save_rules_async()")

        if not self._rules_file:
            raise RuntimeError("No rules_file configured for local file mode")

        self._save_to_file(persistent_rules, wildcard_rules)

    def _save_to_file(
        self, persistent_rules: dict[str, PersistentRule], wildcard_rules: dict[str, FetcherType]
    ) -> None:
        """Save to LocalFile（original子写入：mkstemp + fsync + replace）"""
        assert self._rules_file is not None

        try:
            from myrm_agent_harness.infra.atomic_write import atomic_write

            data = {
                "exact": {domain: rule.to_dict() for domain, rule in persistent_rules.items()},
                "wildcard": {domain: ft.name for domain, ft in wildcard_rules.items()},
            }

            atomic_write(self._rules_file, json.dumps(data, indent=2, ensure_ascii=False))
            logger.warning(f"Saved {len(persistent_rules)} rules to {self._rules_file}")
        except Exception:
            logger.error(f"Failed to save rules to {self._rules_file}", exc_info=True)

    async def _save_to_storage(
        self, persistent_rules: dict[str, PersistentRule], wildcard_rules: dict[str, FetcherType]
    ) -> None:
        """Save to StorageProvider（Cloudoriginal生Mode）"""
        assert self._storage_provider is not None

        from myrm_agent_harness.infra.delivery.storage_metrics import (
            MonitoredStorageCallback,
            get_global_storage_metrics,
        )
        from myrm_agent_harness.infra.delivery.storage_resilience import resilient_storage_operation

        # Serialize is  JSON
        data = {
            "exact": {domain: rule.to_dict() for domain, rule in persistent_rules.items()},
            "wildcard": {domain: ft.name for domain, ft in wildcard_rules.items()},
        }

        async def _write() -> None:
            content = json.dumps(data, indent=2, ensure_ascii=False)
            await self._storage_provider.write_text(self._storage_key, content)

        callback = MonitoredStorageCallback(get_global_storage_metrics())
        try:
            await resilient_storage_operation("write", _write, max_retries=3, callback=callback)
            logger.warning(f"Saved {len(persistent_rules)} rules to storage: {self._storage_key}")
        except Exception:
            logger.error(f"Failed to save rules to storage after retries: {self._storage_key}", exc_info=True)

    def request_save(self, persistent_rules: dict[str, PersistentRule], wildcard_rules: dict[str, FetcherType]) -> None:
        """RequestAsyncSave"""
        self._save_pending = True
        if self._saver_task is None or self._saver_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._saver_task = loop.create_task(self._background_saver(persistent_rules, wildcard_rules))
            except RuntimeError:
                #  no 运行 in  事件循环，SyncSave（OnlyLocalMode）
                if not self._storage_provider:
                    self.save_rules(persistent_rules, wildcard_rules)

    async def _background_saver(
        self,
        persistent_rules: dict[str, PersistentRule],
        wildcard_rules: dict[str, FetcherType],
    ) -> None:
        """BackgroundSave任务"""
        while not self._shutdown_event.is_set():
            await asyncio.sleep(1.0)
            if self._save_pending:
                self._save_pending = False
                await self.save_rules_async(persistent_rules, wildcard_rules)

    def shutdown(self, persistent_rules: dict[str, PersistentRule], wildcard_rules: dict[str, FetcherType]) -> None:
        """Close时SaveState（Sync，OnlyLocalMode）"""
        if self._storage_provider:
            raise RuntimeError("StorageProvider mode requires async shutdown_async()")

        self._shutdown_event.set()
        self.save_rules(persistent_rules, wildcard_rules)

    async def shutdown_async(
        self, persistent_rules: dict[str, PersistentRule], wildcard_rules: dict[str, FetcherType]
    ) -> None:
        """Close时SaveState（Async，SupportAllMode）"""
        self._shutdown_event.set()
        if self._saver_task and not self._saver_task.done():
            self._saver_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._saver_task
        await self.save_rules_async(persistent_rules, wildcard_rules)
