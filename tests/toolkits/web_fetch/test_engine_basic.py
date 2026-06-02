"""CrawlEngine 基础功能测试（不涉及实际网络请求）"""

import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.web_fetch.engine import CrawlEngine


@pytest.mark.asyncio
async def test_engine_initialization_defaults():
    """测试引擎默认初始化"""
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = CrawlEngine(adaptive_router_rules_file=Path(tmpdir) / "test.pkl")

        assert engine._http_fetcher is not None
        assert engine._browser_fetcher is not None
        assert engine._stealth_fetcher is not None
        assert engine._router is not None
        assert engine._pipeline is not None
        assert engine._crawl_cache is not None
        assert engine._fail_cache is not None

        await engine.shutdown()


@pytest.mark.asyncio
async def test_engine_custom_config():
    """测试引擎自定义配置"""
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = CrawlEngine(
            adaptive_router_rules_file=Path(tmpdir) / "test.pkl",
            use_raw_markdown=True,
            cache_ttl=1800,
            cache_maxsize=1000,
            cache_max_bytes=50 * 1024 * 1024,
        )

        assert engine._crawl_cache.ttl == 1800
        assert engine._crawl_cache.maxsize == 1000

        await engine.shutdown()


@pytest.mark.asyncio
async def test_get_router_stats():
    """测试获取路由统计"""
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = CrawlEngine(adaptive_router_rules_file=Path(tmpdir) / "test.pkl")

        stats = engine.get_router_stats()

        assert "cost_learning" in stats
        assert "domain_metrics" in stats

        await engine.shutdown()


@pytest.mark.asyncio
async def test_get_cache_metrics():
    """测试获取缓存指标"""
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = CrawlEngine(adaptive_router_rules_file=Path(tmpdir) / "test.pkl")

        metrics = engine.get_cache_metrics()

        assert "crawl_cache" in metrics
        assert "fail_cache" in metrics

        await engine.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
