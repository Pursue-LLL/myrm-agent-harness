"""StorageProvider弹性机制测试

验证：
- 重试机制（临时错误）
- 永久错误识别
- 指数退避
- 可观测性指标收集
"""

import time

import pytest

from myrm_agent_harness.infra.delivery.storage_metrics import (
    MonitoredStorageCallback,
    StorageMetricsCollector,
)
from myrm_agent_harness.infra.delivery.storage_resilience import (
    PermanentStorageError,
    StorageErrorType,
    TemporaryStorageError,
    _classify_error,
    _is_retryable,
    resilient_storage_operation,
)


class TestErrorClassification:
    """错误分类测试"""

    def test_network_error(self):
        """网络错误分类"""
        error = Exception("Connection timeout")
        assert _classify_error(error) == StorageErrorType.NETWORK
        assert _is_retryable(_classify_error(error))

    def test_permission_error(self):
        """权限错误分类"""
        error = Exception("Permission denied")
        assert _classify_error(error) == StorageErrorType.PERMISSION
        assert not _is_retryable(_classify_error(error))

    def test_not_found_error(self):
        """文件未找到分类"""
        error = FileNotFoundError("File not found")
        assert _classify_error(error) == StorageErrorType.NOT_FOUND
        assert not _is_retryable(_classify_error(error))

    def test_quota_exceeded(self):
        """配额超限分类"""
        error = Exception("Quota exceeded")
        assert _classify_error(error) == StorageErrorType.QUOTA_EXCEEDED
        assert _is_retryable(_classify_error(error))


class TestResilientOperation:
    """弹性操作测试"""

    async def test_success_on_first_attempt(self):
        """第一次尝试成功"""
        collector = StorageMetricsCollector()
        callback = MonitoredStorageCallback(collector)

        async def _operation() -> str:
            return "success"

        result = await resilient_storage_operation(
            "test_op",
            _operation,
            max_retries=3,
            callback=callback,
        )

        assert result == "success"

        stats = collector.get_stats()
        assert stats["test_op"]["success_count"] == 1
        assert stats["test_op"]["failure_count"] == 0
        assert stats["test_op"]["total_retries"] == 0

    async def test_retry_on_temporary_error(self):
        """临时错误重试"""
        collector = StorageMetricsCollector()
        callback = MonitoredStorageCallback(collector)

        attempt_count = 0

        async def _operation() -> str:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise Exception("Connection timeout")
            return "success"

        result = await resilient_storage_operation(
            "test_op",
            _operation,
            max_retries=3,
            initial_backoff_ms=10,
            callback=callback,
        )

        assert result == "success"
        assert attempt_count == 3

        stats = collector.get_stats()
        assert stats["test_op"]["success_count"] == 1
        assert stats["test_op"]["total_retries"] == 2

    async def test_permanent_error_no_retry(self):
        """永久错误不重试"""
        collector = StorageMetricsCollector()
        callback = MonitoredStorageCallback(collector)

        attempt_count = 0

        async def _operation() -> str:
            nonlocal attempt_count
            attempt_count += 1
            raise Exception("Permission denied")

        with pytest.raises(PermanentStorageError) as exc_info:
            await resilient_storage_operation(
                "test_op",
                _operation,
                max_retries=3,
                callback=callback,
            )

        assert "Permanent storage error" in str(exc_info.value)
        assert attempt_count == 1  # 不重试

        stats = collector.get_stats()
        assert stats["test_op"]["failure_count"] == 1
        assert stats["test_op"]["error_types"]["permission"] == 1

    async def test_max_retries_exhausted(self):
        """重试次数用尽"""
        collector = StorageMetricsCollector()
        callback = MonitoredStorageCallback(collector)

        async def _operation() -> str:
            raise Exception("Temporary network error")

        with pytest.raises(TemporaryStorageError) as exc_info:
            await resilient_storage_operation(
                "test_op",
                _operation,
                max_retries=2,
                initial_backoff_ms=10,
                callback=callback,
            )

        assert "failed after 2 retries" in str(exc_info.value)

        stats = collector.get_stats()
        assert stats["test_op"]["failure_count"] == 1
        assert stats["test_op"]["total_retries"] == 2

    async def test_exponential_backoff(self):
        """指数退避验证"""
        attempt_times = []

        async def _operation() -> str:
            attempt_times.append(time.time())
            if len(attempt_times) < 4:
                raise Exception("Network timeout")
            return "success"

        result = await resilient_storage_operation(
            "test_op",
            _operation,
            max_retries=3,
            initial_backoff_ms=100,
            max_backoff_ms=500,
        )

        assert result == "success"
        assert len(attempt_times) == 4

        # 验证退避时间：100ms, 200ms, 400ms
        backoff_1 = (attempt_times[1] - attempt_times[0]) * 1000
        backoff_2 = (attempt_times[2] - attempt_times[1]) * 1000
        backoff_3 = (attempt_times[3] - attempt_times[2]) * 1000

        assert 80 < backoff_1 < 150  # ~100ms
        assert 180 < backoff_2 < 250  # ~200ms
        assert 380 < backoff_3 < 550  # ~400ms (capped at 500ms)


class TestStorageMetricsCollector:
    """指标收集器测试"""

    def test_multiple_operations(self):
        """多个操作统计"""
        collector = StorageMetricsCollector()
        callback = MonitoredStorageCallback(collector)

        from myrm_agent_harness.infra.delivery.storage_resilience import StorageMetrics

        # 记录多个read操作
        callback.on_success(StorageMetrics(operation="read", success=True, duration_ms=50.0, retry_count=0))
        callback.on_success(StorageMetrics(operation="read", success=True, duration_ms=100.0, retry_count=1))

        # 记录一个write失败
        callback.on_error(
            StorageMetrics(
                operation="write",
                success=False,
                duration_ms=200.0,
                error_type=StorageErrorType.NETWORK,
                retry_count=2,
            ),
            Exception("Network error"),
        )

        stats = collector.get_stats()

        # Read统计
        assert stats["read"]["total_count"] == 2
        assert stats["read"]["success_count"] == 2
        assert stats["read"]["failure_count"] == 0
        assert stats["read"]["avg_duration_ms"] == 75.0
        assert stats["read"]["total_retries"] == 1

        # Write统计
        assert stats["write"]["total_count"] == 1
        assert stats["write"]["success_count"] == 0
        assert stats["write"]["failure_count"] == 1
        assert stats["write"]["error_types"]["network"] == 1

    def test_reset(self):
        """重置指标"""
        collector = StorageMetricsCollector()

        from myrm_agent_harness.infra.delivery.storage_resilience import StorageMetrics

        collector.record_operation(StorageMetrics(operation="read", success=True, duration_ms=50.0))

        stats_before = collector.get_stats()
        assert len(stats_before) == 1

        collector.reset()

        stats_after = collector.get_stats()
        assert len(stats_after) == 0
