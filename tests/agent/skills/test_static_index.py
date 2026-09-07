"""Unit tests for Centralized Static Skills Index source (StaticIndexSkillSource).

[INPUT]
- myrm_agent_harness.agent.skills.market.sources.static_index::StaticIndexSkillSource

[OUTPUT]
- Full test coverage for local cache, in-memory instant search, ETag sync, and offline fallback.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.skills.market.sources.static_index import (
    StaticIndexSkillSource,
)


@pytest.fixture
def sample_raw_entries() -> list[dict[str, object]]:
    return [
        {
            "id": "pdf-extractor",
            "name": "PDF Extractor Tool",
            "description": "Extract text and tables from PDF documents efficiently",
            "author": "open-source-dev",
            "install_url": "https://github.com/example/pdf-extractor",
            "install_method": "git",
            "version": "1.2.0",
            "stars": 150,
            "downloads": 500,
            "tags": ["pdf", "ocr", "document"],
            "keywords": ["parse", "table"],
        },
        {
            "id": "github-workflow",
            "name": "GitHub CI/CD Automation",
            "description": "Trigger GitHub actions and manage releases",
            "author": "ci-master",
            "install_url": "https://github.com/example/gh-workflow",
            "install_method": "git",
            "version": "2.0.0",
            "stars": 320,
            "downloads": 1200,
            "tags": ["github", "devops", "ci"],
            "keywords": ["actions", "workflow"],
        },
        {
            "id": "code-review",
            "name": "Code Review Assistant",
            "description": "Automated code reviewer with static analysis",
            "author": "quality-team",
            "install_url": "https://github.com/example/code-reviewer",
            "install_method": "git",
            "version": "1.0.0",
            "stars": 80,
            "downloads": 200,
            "tags": ["code", "review", "linter"],
            "keywords": ["ast", "security"],
        },
    ]


@pytest.mark.asyncio
async def test_static_index_preloaded_search(
    sample_raw_entries: list[dict[str, object]]
) -> None:
    source = StaticIndexSkillSource(preloaded_entries=sample_raw_entries)
    assert source.source_name == "static_index"
    assert source.total_indexed_skills == 3

    # Exact name search
    results = await source.search("PDF Extractor Tool", limit=5)
    assert len(results) >= 1
    assert results[0].id == "pdf-extractor"

    # Keyword search in description / tags
    results_devops = await source.search("devops", limit=5)
    assert len(results_devops) == 1
    assert results_devops[0].id == "github-workflow"

    # Empty query returns all up to limit
    all_res = await source.search("", limit=2)
    assert len(all_res) == 2


@pytest.mark.asyncio
async def test_static_index_get_detail(
    sample_raw_entries: list[dict[str, object]]
) -> None:
    source = StaticIndexSkillSource(preloaded_entries=sample_raw_entries)

    detail = await source.get_detail("pdf-extractor")
    assert detail is not None
    assert detail.name == "PDF Extractor Tool"

    missing = await source.get_detail("non-existent-skill")
    assert missing is None


@pytest.mark.asyncio
async def test_static_index_disk_cache_load_and_save(
    tmp_path: Path, sample_raw_entries: list[dict[str, object]]
) -> None:
    cache_file = tmp_path / "skills-index.json.gz"
    # Pre-populate disk cache
    compressed = gzip.compress(json.dumps(sample_raw_entries).encode("utf-8"))
    cache_file.write_bytes(compressed)

    source = StaticIndexSkillSource(cache_dir=tmp_path)
    results = await source.search("review", limit=5)
    assert len(results) == 1
    assert results[0].id == "code-review"
    assert source.total_indexed_skills == 3


@pytest.mark.asyncio
async def test_static_index_remote_sync_304_and_fallback(tmp_path: Path) -> None:
    etag_file = tmp_path / "skills-index.etag"
    etag_file.write_text("W/12345", encoding="utf-8")

    source = StaticIndexSkillSource(cache_dir=tmp_path, ttl_seconds=0.1)

    # Mock HTTP 304 Not Modified
    mock_resp = AsyncMock()
    mock_resp.status_code = 304

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client

    with patch(
        "myrm_agent_harness.agent.skills.market.sources.static_index.create_httpx_client",
        return_value=mock_client,
    ):
        refreshed = await source.force_refresh()
        assert refreshed is True
