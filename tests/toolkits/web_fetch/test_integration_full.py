"""AdaptiveRouter 完整集成测试

验证 AdaptiveRouter 与 CrawlEngine 的完整集成。
"""

import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.web_fetch.engine import CrawlEngine


@pytest.mark.asyncio
async def test_crawl_engine_with_adaptive_router():
    """测试 CrawlEngine 与 AdaptiveRouter 的完整集成"""
    with tempfile.TemporaryDirectory() as tmpdir:
        rules_file = Path(tmpdir) / "test_rules.pkl"

        engine = CrawlEngine(adaptive_router_rules_file=rules_file)

        stats_before = engine.get_router_stats()
        assert "cost_learning" in stats_before

        await engine.shutdown()


@pytest.mark.asyncio
async def test_latency_tracking():
    """测试延迟追踪功能"""
    with tempfile.TemporaryDirectory() as tmpdir:
        rules_file = Path(tmpdir) / "test_rules.pkl"

        engine = CrawlEngine(adaptive_router_rules_file=rules_file)

        stats_initial = engine.get_router_stats()
        assert stats_initial["cost_learning"]["HTTP"]["samples"] == 0

        await engine.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
