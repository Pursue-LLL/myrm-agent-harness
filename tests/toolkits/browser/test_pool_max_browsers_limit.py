"""Integration tests for browser pool max_browsers limit and forced allocation"""

import contextlib
import shutil

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.pool.config import BrowserPoolConfig

_HAS_CHROMIUM = shutil.which("chromium") is not None or shutil.which("google-chrome") is not None
requires_browser = pytest.mark.skipif(
    not _HAS_CHROMIUM, reason="Chromium/Patchright not installed in this environment"
)

pytestmark = [pytest.mark.integration, requires_browser]


@pytest.mark.asyncio
async def test_max_browsers_limit_forces_allocation(caplog):
    """测试：达到 max_browsers 上限时强制分配到最低负载 Browser"""
    import logging

    config = BrowserPoolConfig(max_concurrent_pages=50)
    pool = GlobalBrowserPool(max_browsers=1, config=config)

    try:
        # 创建多个不同的 context_key，强制填满第一个 Browser 的 contexts
        # 每个 Browser 最多 5 个 contexts（MAX_CONTEXTS_PER_BROWSER）
        acquired_pages = []
        acquired_keys = []

        # 创建 6 个 contexts（超过单个 Browser 的上限 5）
        for i in range(6):
            ctx_key = f"test_context_{i}"
            with caplog.at_level(logging.WARNING):
                page, key = await pool.acquire_page(ContextType.CRAWL, context_key=ctx_key)
                acquired_pages.append(page)
                acquired_keys.append(key)

        # 验证警告日志
        assert "All browsers at max_contexts_per_browser limit" in caplog.text
        assert "forcing context creation on least loaded browser" in caplog.text

        # 验证仍然只有1个Browser
        assert len(pool._browsers) == 1

        # 验证第一个Browser的contexts数量超过了建议上限（但允许）
        assert len(pool._browsers[0].contexts) == 6

    finally:
        for page, key in zip(acquired_pages, acquired_keys, strict=False):
            with contextlib.suppress(Exception):
                await pool.release_page(page, key)
        await pool.shutdown()


@pytest.mark.asyncio
async def test_max_browsers_allows_scale_out():
    """测试：未达到 max_browsers 时允许扩容"""
    config = BrowserPoolConfig(max_concurrent_pages=50)
    pool = GlobalBrowserPool(max_browsers=3, config=config)

    try:
        acquired_pages = []
        acquired_keys = []

        # 创建足够多的高负载场景，触发扩容
        # 每个 context 需要较高负载（> SCALE_OUT_LOAD_THRESHOLD=10）
        for i in range(15):
            ctx_key = f"test_context_{i}"
            page, key = await pool.acquire_page(ContextType.CRAWL, context_key=ctx_key)
            acquired_pages.append(page)
            acquired_keys.append(key)
            # 不释放，保持高负载

        # 验证触发了扩容（应该创建了多个 Browser）
        assert len(pool._browsers) >= 2

    finally:
        for page, key in zip(acquired_pages, acquired_keys, strict=False):
            with contextlib.suppress(Exception):
                await pool.release_page(page, key)
        await pool.shutdown()
