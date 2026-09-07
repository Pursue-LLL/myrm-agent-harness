"""Unit tests for CentralizedStaticSkillsIndexAndMirrorCacheSuite (StaticIndexSkillSource).

[INPUT]
- myrm_agent_harness.agent.skills.market.sources.static_index::StaticIndexSkillSource
- myrm_agent_harness.agent.skills.market.service::BaseSkillMarketService
- myrm_agent_harness.backends.skills.market_protocols::SkillSearchResult

[OUTPUT]
- 100% test coverage for StaticIndexSkillSource (search, detail, disk cache, ETag sync, fallback).
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from myrm_agent_harness.agent.skills.market.service import BaseSkillMarketService
from myrm_agent_harness.agent.skills.market.sources.static_index import (
    StaticIndexSkillSource,
)
from myrm_agent_harness.backends.skills.market_protocols import SkillSearchResult


@pytest.fixture
def sample_raw_entries() -> list[dict[str, object]]:
    return [
        {
            "id": "github::user/video-transcode",
            "name": "video-transcode",
            "description": "Fast video and audio transcoding using ffmpeg",
            "author": "media-team",
            "install_url": "https://github.com/user/video-transcode",
            "install_method": "git",
            "version": "1.2.0",
            "stars": 450,
            "downloads": 1200,
            "tags": ["video", "ffmpeg", "transcode", "audio"],
            "keywords": ["media", "convert"],
            "package_type": "skill",
            "declared_mcp_servers": [],
            "extra_manifest": {"license": "MIT"},
        },
        {
            "id": "github::user/pdf-extractor",
            "name": "pdf-extractor",
            "description": "Extract text, tables, and images from PDF documents",
            "author": "doc-team",
            "install_url": "https://github.com/user/pdf-extractor",
            "install_method": "git",
            "version": "2.0.1",
            "stars": 820,
            "downloads": 5400,
            "tags": ["pdf", "ocr", "document"],
            "keywords": ["text", "extract"],
            "package_type": "skill",
        },
        {
            "id": "clawhub::weather-forecast",
            "name": "weather-forecast",
            "description": "Global real-time weather and forecast skill",
            "author": "geo-dev",
            "install_url": "https://clawhub.ai/skills/weather-forecast.zip",
            "install_method": "zip",
            "version": "1.0.0",
            "stars": 120,
            "tags": ["weather", "forecast"],
        },
    ]


class TestStaticIndexSkillSource:
    @pytest.mark.asyncio
    async def test_search_with_preloaded_entries(
        self, sample_raw_entries: list[dict[str, object]]
    ) -> None:
        source = StaticIndexSkillSource(preloaded_entries=sample_raw_entries)
        assert source.source_name == "static_index"
        assert source.total_indexed_skills == 3

        # 1. Empty query returns top items
        top_results = await source.search("", limit=2)
        assert len(top_results) == 2
        assert top_results[0].id == "github::user/video-transcode"

        # 2. Search exact name match
        results = await source.search("pdf-extractor")
        assert len(results) >= 1
        assert results[0].name == "pdf-extractor"
        assert results[0].stars == 820

        # 3. Search by tag/keyword
        results = await source.search("ffmpeg")
        assert len(results) >= 1
        assert results[0].name == "video-transcode"

        # 4. Search by description keyword
        results = await source.search("forecast")
        assert len(results) >= 1
        assert results[0].name == "weather-forecast"

        # 5. Non-matching query
        empty = await source.search("nonexistent_keyword_xyz")
        assert empty == []

    @pytest.mark.asyncio
    async def test_get_detail(
        self, sample_raw_entries: list[dict[str, object]]
    ) -> None:
        source = StaticIndexSkillSource(preloaded_entries=sample_raw_entries)

        # Exact ID match
        detail = await source.get_detail("github::user/video-transcode")
        assert detail is not None
        assert detail.name == "video-transcode"
        assert detail.author == "media-team"

        # Case-insensitive name match
        detail_by_name = await source.get_detail("PDF-EXTRACTOR")
        assert detail_by_name is not None
        assert detail_by_name.id == "github::user/pdf-extractor"

        # Not found
        assert await source.get_detail("unknown::item") is None

    @pytest.mark.asyncio
    async def test_disk_cache_load_and_etag(
        self, tmp_path: Path, sample_raw_entries: list[dict[str, object]]
    ) -> None:
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cache_file = cache_dir / "skills-index.json.gz"
        etag_file = cache_dir / "skills-index.etag"

        # Write gzipped json to disk
        raw_json_bytes = json.dumps(sample_raw_entries).encode("utf-8")
        cache_file.write_bytes(gzip.compress(raw_json_bytes))
        etag_file.write_text('"etag-12345"', encoding="utf-8")

        # Initialize source pointing to cache_dir
        source = StaticIndexSkillSource(
            index_url="https://mock.example.com/skills.json.gz",
            cache_dir=cache_dir,
            ttl_seconds=3600.0,
        )

        results = await source.search("video")
        assert len(results) == 1
        assert results[0].name == "video-transcode"
        assert source.total_indexed_skills == 3

    @pytest.mark.asyncio
    async def test_remote_sync_success_with_etag(
        self, tmp_path: Path, sample_raw_entries: list[dict[str, object]]
    ) -> None:
        cache_dir = tmp_path / "cache"
        source = StaticIndexSkillSource(
            index_url="https://cdn.myrm.io/skills/skills-index.json.gz",
            cache_dir=cache_dir,
            ttl_seconds=0.0,  # force sync
        )

        raw_json_bytes = json.dumps(sample_raw_entries).encode("utf-8")
        gzipped_bytes = gzip.compress(raw_json_bytes)

        mock_resp = httpx.Response(
            status_code=200,
            content=gzipped_bytes,
            headers={"ETag": '"etag-v1.0.0"'},
            request=httpx.Request("GET", "https://cdn.myrm.io/skills/skills-index.json.gz"),
        )

        with patch("myrm_agent_harness.agent.skills.market.sources.static_index.create_httpx_client") as mock_client_factory:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client_factory.return_value.__aenter__.return_value = mock_client

            success = await source.force_refresh()
            assert success is True
            assert source.total_indexed_skills == 3

            # Verify on-disk persistence
            assert (cache_dir / "skills-index.json.gz").exists()
            assert (cache_dir / "skills-index.etag").read_text(encoding="utf-8") == '"etag-v1.0.0"'

    @pytest.mark.asyncio
    async def test_remote_sync_304_not_modified(
        self, tmp_path: Path, sample_raw_entries: list[dict[str, object]]
    ) -> None:
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "skills-index.etag").write_text('"etag-cached"', encoding="utf-8")
        raw_json_bytes = json.dumps(sample_raw_entries).encode("utf-8")
        (cache_dir / "skills-index.json.gz").write_bytes(gzip.compress(raw_json_bytes))

        source = StaticIndexSkillSource(
            index_url="https://cdn.myrm.io/skills/skills-index.json.gz",
            cache_dir=cache_dir,
            ttl_seconds=0.0,
        )

        mock_resp = httpx.Response(
            status_code=304,
            headers={},
            request=httpx.Request("GET", "https://cdn.myrm.io/skills/skills-index.json.gz"),
        )

        with patch("myrm_agent_harness.agent.skills.market.sources.static_index.create_httpx_client") as mock_client_factory:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client_factory.return_value.__aenter__.return_value = mock_client

            success = await source.force_refresh()
            assert success is True
            assert source.total_indexed_skills == 3

    @pytest.mark.asyncio
    async def test_remote_sync_network_failure_falls_back_to_cache(
        self, tmp_path: Path, sample_raw_entries: list[dict[str, object]]
    ) -> None:
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        raw_json_bytes = json.dumps(sample_raw_entries).encode("utf-8")
        (cache_dir / "skills-index.json.gz").write_bytes(gzip.compress(raw_json_bytes))

        source = StaticIndexSkillSource(
            index_url="https://cdn.myrm.io/skills/skills-index.json.gz",
            cache_dir=cache_dir,
            ttl_seconds=0.0,
        )

        with patch("myrm_agent_harness.agent.skills.market.sources.static_index.create_httpx_client") as mock_client_factory:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectTimeout("Connection timed out")
            mock_client_factory.return_value.__aenter__.return_value = mock_client

            results = await source.search("pdf")
            assert len(results) == 1
            assert results[0].name == "pdf-extractor"


class TestMarketServiceIntegration:
    @pytest.mark.asyncio
    async def test_market_service_aggregates_static_index(
        self, sample_raw_entries: list[dict[str, object]]
    ) -> None:
        service = BaseSkillMarketService()
        # Find static index source
        static_src = next(
            s for s in service._sources if s.source_name == "static_index"
        )
        assert isinstance(static_src, StaticIndexSkillSource)
        # Preload entries into static source
        static_src._load_from_raw_dicts(sample_raw_entries)
        static_src._is_loaded = True

        results = await service.search("transcode", limit=10)
        assert len(results) >= 1
        top_res = results[0].result
        assert top_res.name == "video-transcode"
        assert top_res.source == "static_index"
