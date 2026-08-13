"""Tests for FetchEngine crawl edge cases and cache-mixin branches.

Covers SSRF / domain-allowlist rejection in ``crawl``, bilibili / weixin
fast-path degradation, ``crawl_many`` and ``prefetch_with_retry`` failure
paths, and cache-mixin branches (no-loop worker guard, priority calc,
background revalidation failure / timeout / worker exception).
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.web_fetch.engine import FetchEngine
from myrm_agent_harness.toolkits.web_fetch.engine.types import (
    BackgroundTask,
    CachedDocument,
)
from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import FetchResult


def _engine(tmpdir: str, **kwargs) -> FetchEngine:
    kwargs.setdefault("adaptive_router_rules_file", Path(tmpdir) / "rules.pkl")
    return FetchEngine(**kwargs)


def _doc(text: str = "content") -> Document:
    return Document(page_content=text, metadata={"url": "http://example.com/page"})


BILIBILI_URL = "https://www.bilibili.com/video/BV1xx411c7mD"
WEIXIN_URL = "https://mp.weixin.qq.com/s/abc123"
PLAIN_URL = "http://example.com/page"


# ===================================================================
# base.py — crawl entry guards and fast-path branches
# ===================================================================


class TestCrawlGuardsAndFastPaths:
    @pytest.mark.asyncio
    async def test_crawl_ssrf_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)

            doc = await engine.crawl("http://192.168.1.1/admin")

            assert doc is None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_crawl_domain_allowlist_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(
                tmp, domain_allowlist=SimpleNamespace(is_allowed=lambda host: False)
            )
            engine._allow_private_networks = True

            doc = await engine.crawl(PLAIN_URL)

            assert doc is None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_crawl_bilibili_fastpath_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            engine._allow_private_networks = True
            engine._http_fetcher._session_vault = None

            with patch(
                "myrm_agent_harness.toolkits.web_fetch.engine.base.extract_bilibili_subtitle",
                new=AsyncMock(return_value=_doc("bilibili transcript")),
            ):
                doc = await engine.crawl(BILIBILI_URL)

                assert doc is not None
                assert doc.page_content == "bilibili transcript"
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_crawl_bilibili_fastpath_miss_degrades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            engine._allow_private_networks = True
            degraded = _doc("degraded")
            with (
                patch(
                    "myrm_agent_harness.toolkits.web_fetch.engine.base.extract_bilibili_subtitle",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(
                    engine,
                    "_crawl_with_degradation",
                    new=AsyncMock(return_value=(degraded, None)),
                ),
            ):
                doc = await engine.crawl(BILIBILI_URL)

                assert doc is not None
                assert doc.page_content == "degraded"
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_crawl_weixin_fastpath_miss_degrades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            engine._allow_private_networks = True
            degraded = _doc("weixin degraded")
            with (
                patch(
                    "myrm_agent_harness.toolkits.web_fetch.extractors.weixin_extractor.extract_weixin_article",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(
                    engine,
                    "_crawl_with_degradation",
                    new=AsyncMock(return_value=(degraded, None)),
                ),
            ):
                doc = await engine.crawl(WEIXIN_URL)

                assert doc is not None
                assert doc.page_content == "weixin degraded"
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_set_session_vault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            vault = MagicMock()

            engine.set_session_vault(vault)

            assert engine._http_fetcher._session_vault is vault
            assert engine._browser_fetcher._session_vault is vault
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_set_browser_launch_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)

            engine.set_browser_launch_mode("EXTENSION")

            assert engine._browser_launch_mode == "EXTENSION"
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_crawl_many_reports_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            engine.crawl = AsyncMock(return_value=None)  # type: ignore[method-assign]

            success, failed = await engine.crawl_many(
                ["http://a.example/x", "http://b.example/x"], max_concurrency=2
            )

            assert success == []
            assert len(failed) == 2
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_prefetch_with_retry_handles_exceptions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            engine.crawl = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

            success, failed = await engine.prefetch_with_retry(
                ["http://a.example/x"], max_retries=2, initial_backoff=0.001
            )

            assert success == []
            assert len(failed) == 1
            await engine.shutdown()


# ===================================================================
# cache_mixin.py — worker guard, priority, revalidation branches
# ===================================================================


class TestCacheMixinBranches:
    def test_ensure_workers_started_no_running_loop(self) -> None:
        # 非 async 上下文：get_running_loop 抛 RuntimeError → 提前返回。
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)

            engine._ensure_workers_started()

            assert engine._workers_started is False

    def test_calculate_priority_missing_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)

            assert engine._calculate_priority("unknown-key") == 0

    @pytest.mark.asyncio
    async def test_background_worker_survives_revalidation_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            engine._ensure_workers_started()
            cached = CachedDocument(
                doc=_doc(), etag=None, last_modified=None, cached_at=0.0
            )
            with patch.object(
                engine,
                "_background_revalidate",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ):
                engine._background_queue.put_nowait(
                    BackgroundTask(
                        priority=-1, url=PLAIN_URL, cache_key="k", cached_item=cached
                    )
                )
                for _ in engine._background_workers:
                    engine._background_queue.put_nowait(
                        BackgroundTask(
                            priority=0, url="", cache_key="", cached_item=None
                        )
                    )
                await asyncio.wait_for(
                    asyncio.gather(*engine._background_workers), timeout=5
                )

                assert engine._background_queue.empty()
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_background_revalidate_failure_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            cached = CachedDocument(
                doc=_doc(), etag=None, last_modified=None, cached_at=0.0
            )
            with patch.object(
                engine,
                "_crawl_with_degradation",
                new=AsyncMock(return_value=(None, None)),
            ):
                await engine._background_revalidate(PLAIN_URL, "k", cached)

                assert engine._bg_revalidations_failed == 1
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_background_revalidate_timeout_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _engine(tmp)
            cached = CachedDocument(
                doc=_doc(), etag=None, last_modified=None, cached_at=0.0
            )
            with patch.object(
                engine,
                "_crawl_with_degradation",
                new=AsyncMock(side_effect=asyncio.TimeoutError("timeout")),
            ):
                await engine._background_revalidate(PLAIN_URL, "k", cached)

                assert engine._bg_revalidations_timeout == 1
            await engine.shutdown()
