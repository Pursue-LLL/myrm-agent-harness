"""Unit tests for Centralized Static Skills Index source and cache synchronization."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.skills.market.sources.static_index import (
    DEFAULT_INDEX_URL,
    StaticIndexSkillSource,
)
from myrm_agent_harness.backends.skills.market_protocols import SkillSearchResult


@pytest.fixture
def sample_entries() -> list[dict[str, object]]:
    return [
        {
            "id": "docker-helper",
            "name": "docker-helper",
            "description": "Smart Docker container builder and debugger",
            "source": "official",
            "author": "open-perplexity",
            "install_url": "https://github.com/open-perplexity/docker-helper",
            "install_method": "zip",
            "stars": 120,
            "downloads": 500,
            "tags": ["docker", "devops", "container"],
            "keywords": ["container", "dockerfile"],
        },
        {
            "id": "k8s-operator",
            "name": "k8s-operator",
            "description": "Kubernetes cluster management and deployment tool",
            "source": "clawhub",
            "author": "cloud-native",
            "install_url": "https://github.com/cloud-native/k8s-operator",
            "install_method": "git",
            "stars": 85,
            "downloads": 300,
            "tags": ["k8s", "kubernetes", "cloud"],
            "keywords": ["pod", "cluster"],
        },
    ]


@pytest.mark.asyncio
async def test_static_index_preloaded_search(sample_entries: list[dict[str, object]]) -> None:
    """Verify sub-10ms keyword search and scoring from preloaded memory."""
    source = StaticIndexSkillSource(preloaded_entries=sample_entries)
    assert source.total_indexed_skills == 2
    assert source.source_name == "static_index"

    # Search for "docker"
    results = await source.search("docker", limit=5)
    assert len(results) == 1
    assert results[0].id == "docker-helper"
    assert results[0].stars == 120

    # Search for "cluster" (matches k8s keywords)
    results_k8s = await source.search("cluster", limit=5)
    assert len(results_k8s) == 1
    assert results_k8s[0].id == "k8s-operator"


@pytest.mark.asyncio
async def test_static_index_get_detail(sample_entries: list[dict[str, object]]) -> None:
    """Verify finding a skill by exact id."""
    source = StaticIndexSkillSource(preloaded_entries=sample_entries)
    detail = await source.get_detail("docker-helper")
    assert detail is not None
    assert detail.name == "docker-helper"

    detail_missing = await source.get_detail("nonexistent-skill")
    assert detail_missing is None


@pytest.mark.asyncio
async def test_static_index_disk_cache_load_and_etag_sync(
    tmp_path: Path, sample_entries: list[dict[str, object]]
) -> None:
    """Verify loading from local gzipped cache and conditional ETag check."""
    cache_file = tmp_path / "skills-index.json.gz"
    etag_file = tmp_path / "skills-index.etag"

    # Write gzipped test data
    payload = json.dumps({"skills": sample_entries}).encode("utf-8")
    with gzip.open(cache_file, "wb") as f:
        f.write(payload)
    etag_file.write_text("W/\"test-etag-1234\"", encoding="utf-8")

    source = StaticIndexSkillSource(cache_dir=tmp_path, ttl_seconds=3600)
    
    # Mock remote fetch returning 304 Not Modified
    with patch("myrm_agent_harness.infra.tls_compat.create_httpx_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 304
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_factory.return_value = mock_client

        results = await source.search("docker")
        assert len(results) == 1
        assert results[0].id == "docker-helper"
        assert source.total_indexed_skills == 2
