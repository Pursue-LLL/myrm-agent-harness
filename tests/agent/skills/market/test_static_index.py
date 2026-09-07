"""Unit tests for Centralized Static Skills Index and Mirror Cache.

[INPUT]
- myrm_agent_harness.agent.skills.market.sources.static_index::StaticIndexSkillSource
- myrm_agent_harness.agent.skills.market.service::BaseSkillMarketService

[OUTPUT]
- TestStaticIndexSkillSource: tests for ETag 304 caching, gzip uncompress, local fallback, relevance scoring
- TestMarketServiceStaticIndexIntegration: tests for default source mounting and priority ranking

[POS]
Test suite for static skills index source and market service aggregation.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import respx
import httpx

from myrm_agent_harness.agent.skills.market.service import BaseSkillMarketService
from myrm_agent_harness.agent.skills.market.sources.static_index import (
    StaticIndexSkillSource,
)


@pytest.fixture
def sample_skills_json() -> list[dict[str, object]]:
    return [
        {
            "id": "open-researcher",
            "name": "Open Researcher",
            "description": "Deep web search and paper synthesis skill",
            "author": "open-perplexity",
            "install_url": "https://github.com/open-perplexity/skills/tree/main/researcher",
            "install_method": "git",
            "version": "1.2.0",
            "stars": 450,
            "downloads": 12000,
            "tags": ["research", "search", "web"],
            "keywords": ["arxiv", "google-scholar"],
        },
        {
            "id": "code-refactor-expert",
            "name": "Code Refactor Expert",
            "description": "AST based clean refactoring tool for Python and TS",
            "author": "dev-community",
            "install_url": "https://github.com/dev/refactor",
            "install_method": "git",
            "version": "2.0.0",
            "stars": 820,
            "downloads": 30000,
            "tags": ["coding", "refactor"],
            "keywords": ["ast", "clean-code"],
        },
    ]


@pytest.mark.asyncio
class TestStaticIndexSkillSource:
    """Test StaticIndexSkillSource caching, sync, and offline instant search."""

    async def test_search_from_preloaded_entries(
        self, sample_skills_json: list[dict[str, object]]
    ) -> None:
        source = StaticIndexSkillSource(preloaded_entries=sample_skills_json)
        assert source.total_indexed_skills == 2

        results = await source.search("researcher")
        assert len(results) == 1
        assert results[0].id == "open-researcher"
        assert results[0].source == "static_index"

        results_kw = await source.search("clean-code")
        assert len(results_kw) == 1
        assert results_kw[0].id == "code-refactor-expert"

    async def test_load_from_local_gzip_cache(
        self, tmp_path: Path, sample_skills_json: list[dict[str, object]]
    ) -> None:
        cache_file = tmp_path / "skills-index.json.gz"
        raw_bytes = json.dumps(sample_skills_json).encode("utf-8")
        cache_file.write_bytes(gzip.compress(raw_bytes))

        source = StaticIndexSkillSource(
            index_url="https://mock.cdn/skills.json.gz",
            cache_dir=tmp_path,
        )

        detail = await source.get_detail("open-researcher")
        assert detail is not None
        assert detail.name == "Open Researcher"
        assert detail.stars == 450

    @respx.mock
    async def test_sync_remote_index_200_and_etag(
        self, tmp_path: Path, sample_skills_json: list[dict[str, object]]
    ) -> None:
        url = "https://mock.cdn/skills-index.json.gz"
        compressed = gzip.compress(json.dumps(sample_skills_json).encode("utf-8"))

        respx.get(url).respond(
            status_code=200,
            content=compressed,
            headers={"ETag": '"abc123etag"'},
        )

        source = StaticIndexSkillSource(
            index_url=url,
            cache_dir=tmp_path,
        )

        results = await source.search("refactor")
        assert len(results) == 1
        assert results[0].id == "code-refactor-expert"

        etag_file = tmp_path / "skills-index.etag"
        assert etag_file.exists()
        assert etag_file.read_text(encoding="utf-8") == '"abc123etag"'

    @respx.mock
    async def test_sync_remote_index_304_not_modified(
        self, tmp_path: Path, sample_skills_json: list[dict[str, object]]
    ) -> None:
        url = "https://mock.cdn/skills-index.json.gz"
        etag_file = tmp_path / "skills-index.etag"
        etag_file.write_text('"existing-etag"', encoding="utf-8")

        # Prepare local cache
        cache_file = tmp_path / "skills-index.json.gz"
        cache_file.write_bytes(gzip.compress(json.dumps(sample_skills_json).encode("utf-8")))

        respx.get(url).respond(status_code=304)

        source = StaticIndexSkillSource(
            index_url=url,
            cache_dir=tmp_path,
        )

        results = await source.search("research")
        assert len(results) == 1
        assert results[0].id == "open-researcher"


@pytest.mark.asyncio
class TestMarketServiceStaticIndexIntegration:
    """Test BaseSkillMarketService default data source ordering and static index integration."""

    async def test_static_index_is_mounted_by_default(self) -> None:
        service = BaseSkillMarketService()
        source_names = [s.source_name for s in service._sources]
        assert "static_index" in source_names
        assert "clawhub" in source_names
        assert "github" in source_names

    async def test_search_ranks_static_index_efficiently(
        self, sample_skills_json: list[dict[str, object]]
    ) -> None:
        service = BaseSkillMarketService()
        static_src = StaticIndexSkillSource(preloaded_entries=sample_skills_json)

        # Replace static source with preloaded instance
        service._sources = [s for s in service._sources if s.source_name != "static_index"]
        service._sources.insert(0, static_src)

        results = await service.search("researcher", limit=5)
        assert len(results) >= 1
        top_match = next((r for r in results if r.result.id == "open-researcher"), None)
        assert top_match is not None
        assert top_match.result.source == "static_index"
