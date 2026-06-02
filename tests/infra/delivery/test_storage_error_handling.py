"""StorageProvider错误处理集成测试

验证DeliveryQueue在StorageProvider失败时的行为：
- 保存失败时的重试
- 加载失败时的降级（返回空列表）
- 删除失败时的优雅处理
"""

import asyncio
from pathlib import Path

from myrm_agent_harness.infra.delivery.queue import DeliveryQueue
from myrm_agent_harness.infra.delivery.storage_metrics import get_global_storage_metrics
from myrm_agent_harness.toolkits.storage.base import FileInfo, StorageProvider


class FlakyStorageProvider(StorageProvider):
    """模拟不稳定的StorageProvider（用于测试重试机制）"""

    def __init__(self, fail_count: int = 2):
        super().__init__()
        self._fail_count = fail_count
        self._write_attempts = 0
        self._read_attempts = 0
        self._delete_attempts = 0
        self._storage: dict[str, bytes] = {}

    async def read(self, key: str) -> bytes:
        self._read_attempts += 1
        if self._read_attempts <= self._fail_count:
            raise Exception("Network timeout")
        if key not in self._storage:
            raise FileNotFoundError(f"Key not found: {key}")
        return self._storage[key]

    async def write(self, key: str, data: bytes) -> None:
        self._write_attempts += 1
        if self._write_attempts <= self._fail_count:
            raise Exception("Connection error")
        self._storage[key] = data

    async def delete(self, key: str) -> None:
        self._delete_attempts += 1
        if self._delete_attempts <= self._fail_count:
            raise Exception("Network timeout")
        if key in self._storage:
            del self._storage[key]
        else:
            raise FileNotFoundError(f"Key not found: {key}")

    async def list(self, prefix: str = "", recursive: bool = True) -> list[str]:
        return [k for k in self._storage if k.startswith(prefix)]

    async def exists(self, key: str) -> bool:
        return key in self._storage

    async def info(self, key: str) -> FileInfo:
        if key not in self._storage:
            raise FileNotFoundError(f"Key not found: {key}")
        return FileInfo(key=key, size=len(self._storage[key]))

    async def copy(self, src_key: str, dst_key: str) -> None:
        if src_key not in self._storage:
            raise FileNotFoundError(f"Source key not found: {src_key}")
        self._storage[dst_key] = self._storage[src_key]

    async def move(self, src_key: str, dst_key: str) -> None:
        if src_key not in self._storage:
            raise FileNotFoundError(f"Source key not found: {src_key}")
        self._storage[dst_key] = self._storage[src_key]
        del self._storage[src_key]

    async def is_dir(self, key: str) -> bool:
        return False

    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        return f"mock://storage/{key}"

    async def read_text(self, key: str, encoding: str = "utf-8") -> str:
        data = await self.read(key)
        return data.decode(encoding)

    async def write_text(self, key: str, text: str, encoding: str = "utf-8") -> None:
        await self.write(key, text.encode(encoding))


class TestStorageProviderErrorHandling:
    """StorageProvider错误处理测试"""

    async def test_save_with_retry(self, tmp_path: Path):
        """保存失败时自动重试"""
        storage = FlakyStorageProvider(fail_count=2)
        delivered = []

        async def deliver_fn(channel: str, recipient: str, content: dict) -> None:
            delivered.append((channel, recipient, content))

        queue = DeliveryQueue(
            base_dir=tmp_path,
            deliver_fn=deliver_fn,
            storage_provider=storage,
            batch_timeout_ms=100,
        )

        try:
            await queue.start()

            # 入队消息（保存会失败2次）
            await queue.enqueue("test", "user1", {"msg": "hello"})

            # 等待投递
            await asyncio.sleep(0.5)

            # 验证消息已投递
            assert len(delivered) == 1
            assert delivered[0] == ("test", "user1", {"msg": "hello"})

            # 验证重试了3次才成功（前2次失败）
            assert storage._write_attempts == 3

        finally:
            await queue.stop()

    async def test_load_failure_graceful_degradation(self, tmp_path: Path):
        """加载失败时优雅降级（返回空列表，队列正常启动）"""

        class LoadFailStorage(FlakyStorageProvider):
            """只让list操作失败"""

            async def list(self, prefix: str = "", recursive: bool = True) -> list[str]:
                raise Exception("Network timeout during list")

        storage = LoadFailStorage(fail_count=0)  # write/delete正常
        delivered = []

        async def deliver_fn(channel: str, recipient: str, content: dict) -> None:
            delivered.append((channel, recipient, content))

        queue = DeliveryQueue(
            base_dir=tmp_path,
            deliver_fn=deliver_fn,
            storage_provider=storage,
            batch_timeout_ms=100,
        )

        try:
            # start会尝试加载，但应该优雅降级（返回空列表）
            await queue.start()

            # 队列仍应正常工作
            await queue.enqueue("test", "user1", {"msg": "hello"})
            await asyncio.sleep(0.3)

            assert len(delivered) == 1

        finally:
            await queue.stop()

    async def test_delete_failure_logged_but_not_fatal(self, tmp_path: Path):
        """删除失败时记录日志但不影响投递"""
        storage = FlakyStorageProvider(fail_count=10)
        delivered = []

        async def deliver_fn(channel: str, recipient: str, content: dict) -> None:
            delivered.append((channel, recipient, content))

        queue = DeliveryQueue(
            base_dir=tmp_path,
            deliver_fn=deliver_fn,
            storage_provider=storage,
            batch_timeout_ms=100,
        )

        try:
            await queue.start()

            # 手动写入一条消息到storage（模拟待恢复的消息）
            storage._delete_attempts = 0  # 重置计数器
            storage._write_attempts = 100  # 跳过write失败

            await queue.enqueue("test", "user1", {"msg": "hello"})
            await asyncio.sleep(0.3)

            # 消息应该被投递
            assert len(delivered) == 1

            # 删除会失败，但不影响投递

        finally:
            await queue.stop()


class TestStorageMetrics:
    """StorageProvider可观测性指标测试"""

    async def test_metrics_collection(self, tmp_path: Path):
        """验证指标收集"""
        metrics = get_global_storage_metrics()
        metrics.reset()

        storage = FlakyStorageProvider(fail_count=1)
        delivered = []

        async def deliver_fn(channel: str, recipient: str, content: dict) -> None:
            delivered.append((channel, recipient, content))

        queue = DeliveryQueue(
            base_dir=tmp_path,
            deliver_fn=deliver_fn,
            storage_provider=storage,
            batch_timeout_ms=100,
        )

        try:
            await queue.start()
            await queue.enqueue("test", "user1", {"msg": "hello"})
            await asyncio.sleep(0.5)

            stats = metrics.get_stats()

            # 应该有write操作（保存消息）
            assert "write" in stats
            assert stats["write"]["success_count"] >= 1

            # 应该有delete操作（确认投递）
            if "delete" in stats:
                assert stats["delete"]["total_count"] >= 1

        finally:
            await queue.stop()
