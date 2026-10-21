"""测试DomainMetricsManager的StorageProvider支持"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.storage.local import LocalStorageBackend
from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import FetcherType
from myrm_agent_harness.toolkits.web_fetch.router.domain_metrics import DomainMetricsManager


@pytest.mark.asyncio
async def test_storage_provider_async_load_save(tmp_path: Path):
    """测试StorageProvider模式的异步加载和保存"""
    storage_provider = LocalStorageBackend(tmp_path / "storage")
    storage_key = "web_fetch/domain_metrics.json"

    # 创建manager（StorageProvider模式）
    manager = DomainMetricsManager(
        storage_provider=storage_provider,
        storage_key=storage_key,
    )

    # 记录一些数据
    metrics = manager.get_or_create("example.com")
    metrics.record_fetcher_result(FetcherType.HTTP, True, 100.0)
    metrics.record_fetcher_result(FetcherType.BROWSER, False, 500.0)

    # 异步保存
    await manager._save_metrics_async()

    # 验证数据已保存到StorageProvider
    data = await storage_provider.read(storage_key)
    assert b"example.com" in data

    # 创建新manager并异步加载
    manager2 = DomainMetricsManager(
        storage_provider=storage_provider,
        storage_key=storage_key,
    )
    await manager2.load_metrics_async()

    # 验证数据正确恢复
    assert "example.com" in manager2._metrics
    loaded_metrics = manager2.get("example.com")
    assert loaded_metrics is not None
    assert loaded_metrics.fetcher_total_counts[FetcherType.HTTP] == 1
    assert loaded_metrics.fetcher_success_counts[FetcherType.HTTP] == 1
    assert loaded_metrics.fetcher_total_counts[FetcherType.BROWSER] == 1
    assert loaded_metrics.fetcher_success_counts[FetcherType.BROWSER] == 0


@pytest.mark.asyncio
async def test_storage_provider_background_save(tmp_path: Path):
    """测试StorageProvider模式的后台保存"""
    storage_provider = LocalStorageBackend(tmp_path / "storage")
    storage_key = "web_fetch/domain_metrics.json"

    manager = DomainMetricsManager(
        storage_provider=storage_provider,
        storage_key=storage_key,
    )

    # 记录数据并请求保存
    metrics = manager.get_or_create("test.com")
    metrics.record_fetcher_result(FetcherType.HTTP, True, 50.0)
    manager.request_save()

    # 等待后台保存完成
    await asyncio.sleep(2.0)

    # 验证数据已保存
    try:
        data = await storage_provider.read(storage_key)
        assert b"test.com" in data
    except FileNotFoundError:
        pytest.fail("Background save did not complete")


@pytest.mark.asyncio
async def test_storage_provider_shutdown_async(tmp_path: Path):
    """测试StorageProvider模式的异步关闭"""
    storage_provider = LocalStorageBackend(tmp_path / "storage")
    storage_key = "web_fetch/domain_metrics.json"

    manager = DomainMetricsManager(
        storage_provider=storage_provider,
        storage_key=storage_key,
    )

    # 记录数据
    metrics = manager.get_or_create("shutdown-test.com")
    metrics.record_fetcher_result(FetcherType.STEALTH, True, 200.0)

    # 异步关闭（应该保存数据）
    await manager.shutdown_async()

    # 验证数据已保存
    data = await storage_provider.read(storage_key)
    assert b"shutdown-test.com" in data


def test_local_file_mode_still_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """验证本地文件模式仍然正常工作"""
    # 移除测试环境标记，允许正常加载
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    storage_path = tmp_path / "domain_metrics.json"

    # 本地文件模式
    manager = DomainMetricsManager(storage_path=storage_path)

    metrics = manager.get_or_create("local-test.com")
    metrics.record_fetcher_result(FetcherType.HTTP, True, 75.0)

    # 同步保存
    manager._save_metrics()

    # 验证文件存在
    assert storage_path.exists()

    # 重新加载
    manager2 = DomainMetricsManager(storage_path=storage_path)
    assert "local-test.com" in manager2._metrics
