"""全链路连接池枯竭防御与 Socket 租约中枢单元测试.

覆盖软限制抬升边界、FD 水位监测与反压判定、连接硬配额隔离、排队超时防死锁及危急熔断拒绝.
"""

from __future__ import annotations

import resource
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.runtime.socket_lease_governor import (
    FDWatermarkSentinel,
    FDWatermarkStatus,
    GovernorConfig,
    LeaseAcquisitionTimeoutError,
    ResourceLeaseType,
    ResourceOverloadError,
    SocketLeaseGovernor,
    get_nofile_limits,
    raise_nofile_soft_limit,
)


def test_raise_nofile_soft_limit_boundaries() -> None:
    """验证 RLIMIT_NOFILE 软限制自适应抬升的边界与优雅降级."""
    # 1. 真实系统下读取验证
    soft, hard = get_nofile_limits()
    assert isinstance(soft, int)
    assert isinstance(hard, int)

    # 2. 模拟当前软限制低于目标 (256 -> 4096, 硬限制 1048576)
    with (
        patch("resource.getrlimit", return_value=(256, 1048576)),
        patch("resource.setrlimit") as mock_setrlimit,
    ):
        new_soft, new_hard = raise_nofile_soft_limit(target=4096)
        assert new_soft == 4096
        assert new_hard == 1048576
        mock_setrlimit.assert_called_once_with(resource.RLIMIT_NOFILE, (4096, 1048576))

    # 3. 模拟当前软限制已高于目标 (8192 -> 4096)，应保持不变绝不降级
    with (
        patch("resource.getrlimit", return_value=(8192, 1048576)),
        patch("resource.setrlimit") as mock_setrlimit,
    ):
        new_soft, new_hard = raise_nofile_soft_limit(target=4096)
        assert new_soft == 8192
        mock_setrlimit.assert_not_called()

    # 4. 模拟硬限制封顶 (软 256, 硬 1024, 目标 4096)，应以硬限制 1024 封顶
    with (
        patch("resource.getrlimit", return_value=(256, 1024)),
        patch("resource.setrlimit") as mock_setrlimit,
    ):
        new_soft, new_hard = raise_nofile_soft_limit(target=4096)
        assert new_soft == 1024
        mock_setrlimit.assert_called_once_with(resource.RLIMIT_NOFILE, (1024, 1024))

    # 5. 模拟 setrlimit 权限不足抛出 PermissionError，应安全降级不崩溃
    with (
        patch("resource.getrlimit", return_value=(256, 1048576)),
        patch("resource.setrlimit", side_effect=PermissionError("Operation not permitted")),
    ):
        new_soft, new_hard = raise_nofile_soft_limit(target=4096)
        assert new_soft == 256  # 优雅降级保留原值


def test_fd_watermark_sentinel_sampling_and_status() -> None:
    """验证 FDWatermarkSentinel 采样判定与毫秒短时缓存."""
    config = GovernorConfig(fd_warning_ratio=0.75, fd_critical_ratio=0.85)
    sentinel = FDWatermarkSentinel(config=config, cache_ttl_ms=50.0)

    # 模拟软限制为 1000
    with patch(
        "myrm_agent_harness.runtime.socket_lease_governor.fd_watermark_sentinel.get_nofile_limits",
        return_value=(1000, 2000),
    ):
        # 1. 占用 500 (50%) -> NORMAL
        with patch.object(sentinel, "count_open_fds", return_value=500):
            snap1 = sentinel.sample_metrics(force_refresh=True)
            assert snap1.allocated_fds == 500
            assert snap1.usage_ratio == 0.5
            assert snap1.status == FDWatermarkStatus.NORMAL
            assert sentinel.is_backpressure_active() is False

        # 2. 占用 800 (80%) -> WARNING
        with patch.object(sentinel, "count_open_fds", return_value=800):
            snap2 = sentinel.sample_metrics(force_refresh=True)
            assert snap2.status == FDWatermarkStatus.WARNING
            assert sentinel.is_backpressure_active() is False

        # 3. 占用 900 (90%) -> CRITICAL_BACKPRESSURE
        with patch.object(sentinel, "count_open_fds", return_value=900):
            snap3 = sentinel.sample_metrics(force_refresh=True)
            assert snap3.status == FDWatermarkStatus.CRITICAL_BACKPRESSURE
            assert sentinel.is_backpressure_active() is True


@pytest.mark.asyncio
async def test_socket_lease_governor_acquire_and_release() -> None:
    """验证 SocketLeaseGovernor 正常租借、凭证发放与退出自动释放."""
    config = GovernorConfig(max_http_sockets=4)
    governor = SocketLeaseGovernor(config=config)

    assert governor.get_active_leases(ResourceLeaseType.HTTP_SOCKET) == 0

    async with governor.acquire_lease(ResourceLeaseType.HTTP_SOCKET) as ticket:
        assert ticket.resource_type == ResourceLeaseType.HTTP_SOCKET
        assert ticket.ticket_id.startswith("lease_")
        assert governor.get_active_leases(ResourceLeaseType.HTTP_SOCKET) == 1
        assert governor.total_acquired_count == 1

    # 离开上下文后立即归还
    assert governor.get_active_leases(ResourceLeaseType.HTTP_SOCKET) == 0


@pytest.mark.asyncio
async def test_socket_lease_governor_timeout_queue() -> None:
    """验证租约配额打满时超时等待与安全防死锁机制."""
    config = GovernorConfig(max_db_connections=2)
    governor = SocketLeaseGovernor(config=config)

    # 占满 2 个 DB 连接
    async with (
        governor.acquire_lease(ResourceLeaseType.DATABASE_CONNECTION) as _t1,
        governor.acquire_lease(ResourceLeaseType.DATABASE_CONNECTION) as _t2,
    ):
        assert governor.get_active_leases(ResourceLeaseType.DATABASE_CONNECTION) == 2

        # 第 3 个请求因配额满，在 0.05s 超时后抛出 LeaseAcquisitionTimeoutError
        with pytest.raises(LeaseAcquisitionTimeoutError) as exc_info:
            async with governor.acquire_lease(
                ResourceLeaseType.DATABASE_CONNECTION,
                timeout=0.05,
            ):
                pass
        assert exc_info.value.resource_type == ResourceLeaseType.DATABASE_CONNECTION
        assert governor.total_timeout_count == 1

    # 退出前两个上下文后，配额释放
    assert governor.get_active_leases(ResourceLeaseType.DATABASE_CONNECTION) == 0

    # 后续请求立刻成功
    async with governor.acquire_lease(ResourceLeaseType.DATABASE_CONNECTION) as t3:
        assert t3.resource_type == ResourceLeaseType.DATABASE_CONNECTION


@pytest.mark.asyncio
async def test_socket_lease_governor_backpressure_rejection() -> None:
    """验证处于 CRITICAL_BACKPRESSURE 时普通请求被熔断拒绝，特权请求允许通行."""
    mock_sentinel = MagicMock(spec=FDWatermarkSentinel)
    mock_sentinel.is_backpressure_active.return_value = True
    mock_sentinel.sample_metrics.return_value = MagicMock(
        usage_ratio=0.88,
        allocated_fds=880,
        soft_limit=1000,
    )

    governor = SocketLeaseGovernor(sentinel=mock_sentinel)

    # 1. 普通非特权请求直接抛出 ResourceOverloadError 熔断
    with pytest.raises(ResourceOverloadError) as exc_info:
        async with governor.acquire_lease(
            ResourceLeaseType.HTTP_SOCKET,
            priority=False,
        ):
            pass
    assert exc_info.value.current_fd_ratio == 0.88
    assert governor.total_rejected_count == 1

    # 2. 特权请求（priority=True）绕过反压限制正常获取
    async with governor.acquire_lease(
        ResourceLeaseType.HTTP_SOCKET,
        priority=True,
    ) as ticket:
        assert ticket.resource_type == ResourceLeaseType.HTTP_SOCKET
