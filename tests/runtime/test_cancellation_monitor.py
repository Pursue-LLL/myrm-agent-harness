"""Tests for CancellationMonitor and create_cancellation_context"""

import asyncio

import pytest

from myrm_agent_harness.utils.runtime.cancellation import (
    CancellationMonitor,
    CancellationToken,
    create_cancellation_context,
)


class TestCancellationMonitor:
    """Tests for CancellationMonitor"""

    @pytest.mark.asyncio
    async def test_monitor_detects_disconnect(self):
        """测试：监控器检测到客户端断开连接"""
        token = CancellationToken(request_id="test")
        disconnect_count = 0

        async def disconnect_checker() -> bool:
            nonlocal disconnect_count
            disconnect_count += 1
            return disconnect_count >= 2  # 第2次检查时返回True

        monitor = CancellationMonitor(token, disconnect_checker, check_interval=0.1)

        await monitor.start()
        await asyncio.sleep(0.3)

        assert token.is_cancelled
        assert token.cancel_reason == "client_disconnected"
        await monitor.stop()

    @pytest.mark.asyncio
    async def test_monitor_stops_gracefully(self):
        """测试：监控器可以正常停止"""
        token = CancellationToken(request_id="test")

        async def no_disconnect() -> bool:
            return False

        monitor = CancellationMonitor(token, no_disconnect, check_interval=0.1)

        await monitor.start()
        await asyncio.sleep(0.15)
        await monitor.stop()

        assert not token.is_cancelled

    @pytest.mark.asyncio
    async def test_monitor_handles_already_done_task(self):
        """测试：stop 时任务已完成不抛异常"""
        token = CancellationToken(request_id="test")

        async def instant_disconnect() -> bool:
            return True

        monitor = CancellationMonitor(token, instant_disconnect, check_interval=0.05)

        await monitor.start()
        await asyncio.sleep(0.1)

        # 任务应该已完成
        assert token.is_cancelled

        # stop 应该正常返回（不抛异常）
        await monitor.stop()


class TestCreateCancellationContext:
    """Tests for create_cancellation_context factory"""

    @pytest.mark.asyncio
    async def test_creates_token_and_monitor_factory(self):
        """测试：创建 token 和 monitor 工厂函数"""
        token, create_monitor = create_cancellation_context("test-req")

        assert isinstance(token, CancellationToken)
        assert token.request_id == "test-req"
        assert not token.is_cancelled

        # 创建 monitor
        async def disconnect_checker() -> bool:
            return False

        monitor = create_monitor(disconnect_checker)
        assert isinstance(monitor, CancellationMonitor)

    @pytest.mark.asyncio
    async def test_monitor_shares_token(self):
        """测试：monitor 使用同一个 token"""
        token, create_monitor = create_cancellation_context("test-req")

        async def disconnect_checker() -> bool:
            return True

        monitor = create_monitor(disconnect_checker)

        await monitor.start()
        await asyncio.sleep(0.1)

        # token 应该被取消
        assert token.is_cancelled

        await monitor.stop()

    def test_default_request_id(self):
        """测试：request_id 默认为 'unknown'"""
        token, _ = create_cancellation_context()
        assert token.request_id == "unknown"
