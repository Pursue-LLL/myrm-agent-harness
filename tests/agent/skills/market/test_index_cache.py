"""Unit tests for the offline-first skills index cache.

[INPUT]
- myrm_agent_harness.agent.skills.market.index_cache

[OUTPUT]
- pytest suite covering disk round-trips, TTL validity, and in-memory
  token scoring across name, description, keywords, and tags.

[POS]
myrm-agent-harness/tests/agent/skills/market/test_index_cache.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from myrm_agent_harness.agent.skills.market.index_cache import SkillsIndexCache


def _item(skill_id: str, name: str, **kwargs: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": skill_id,
        "name": name,
        "description": f"about {name}",
        "source": "index",
        "author": "acme",
        "install_url": "https://example.invalid/a.zip",
        "install_method": "zip",
        "version": "1.0.0",
        "stars": 100,
        "downloads": 10,
        "tags": [],
    }
    payload.update(kwargs)
    return payload


@pytest.fixture
def cache(tmp_path: Path) -> SkillsIndexCache:
    return SkillsIndexCache(cache_dir=tmp_path, ttl_seconds=3600)


class TestLoadCachedIndex:
    def test_missing_file_returns_empty(self, cache: SkillsIndexCache) -> None:
        assert cache.load_cached_index() == []

    def test_loads_wrapped_payload(self, cache: SkillsIndexCache) -> None:
        cache.save_index([_item("a", "Alpha")])
        records = cache.load_cached_index()
        assert [r.id for r in records] == ["a"]
        assert records[0].name == "Alpha"
        assert records[0].package_type == "skill"

    def test_loads_bare_list_payload(self, cache: SkillsIndexCache) -> None:
        cache.cache_dir.mkdir(parents=True, exist_ok=True)
        (cache.cache_dir / "skills-index.json").write_text(json.dumps([_item("a", "Alpha")]), encoding="utf-8")
        assert len(cache.load_cached_index()) == 1

    def test_skips_non_dict_and_incomplete_entries(self, cache: SkillsIndexCache) -> None:
        cache.cache_dir.mkdir(parents=True, exist_ok=True)
        (cache.cache_dir / "skills-index.json").write_text(
            json.dumps({"skills": ["junk", {"id": "", "name": "x"}, {"id": "ok", "name": "Ok"}]}),
            encoding="utf-8",
        )
        assert [r.id for r in cache.load_cached_index()] == ["ok"]

    def test_rejects_non_list_payload(self, cache: SkillsIndexCache) -> None:
        cache.cache_dir.mkdir(parents=True, exist_ok=True)
        (cache.cache_dir / "skills-index.json").write_text(json.dumps("scalar"), encoding="utf-8")
        assert cache.load_cached_index() == []

    def test_corrupt_json_returns_empty(self, cache: SkillsIndexCache) -> None:
        cache.cache_dir.mkdir(parents=True, exist_ok=True)
        (cache.cache_dir / "skills-index.json").write_text("{not json", encoding="utf-8")
        assert cache.load_cached_index() == []

    def test_populates_optional_metadata(self, cache: SkillsIndexCache) -> None:
        cache.save_index(
            [
                _item(
                    "a",
                    "Alpha",
                    readme_url="https://example.invalid/a",
                    subdirectory="skills/a",
                    package_type="agent_plugin",
                    keywords=["k1"],
                    declared_mcp_servers=["fs"],
                )
            ]
        )
        record = cache.load_cached_index()[0]
        assert record.readme_url == "https://example.invalid/a"
        assert record.subdirectory == "skills/a"
        assert record.package_type == "agent_plugin"
        assert record.keywords == ["k1"]
        assert record.declared_mcp_servers == ["fs"]


class TestSaveIndex:
    def test_creates_cache_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "cache"
        cache = SkillsIndexCache(cache_dir=target, ttl_seconds=3600)
        cache.save_index([_item("a", "Alpha")])
        assert (target / "skills-index.json").exists()

    def test_writes_meta_with_etag(self, cache: SkillsIndexCache) -> None:
        cache.save_index([_item("a", "Alpha")], etag="etag-9")
        meta = json.loads((cache.cache_dir / "skills-index.meta.json").read_text(encoding="utf-8"))
        assert meta["etag"] == "etag-9"

    def test_omits_meta_without_etag(self, cache: SkillsIndexCache) -> None:
        cache.save_index([_item("a", "Alpha")])
        assert not (cache.cache_dir / "skills-index.meta.json").exists()

    def test_save_failure_is_swallowed(self, cache: SkillsIndexCache) -> None:
        cache.cache_dir.mkdir(parents=True, exist_ok=True)
        (cache.cache_dir / "skills-index.json").write_text("i am a directory", encoding="utf-8")
        (cache.cache_dir / "skills-index.json").unlink()
        (cache.cache_dir / "skills-index.json").mkdir()
        cache.save_index([_item("a", "Alpha")])
        assert cache.load_cached_index() == []


class TestCacheValidity:
    def test_missing_index_invalid(self, cache: SkillsIndexCache) -> None:
        assert cache.is_cache_valid() is False

    def test_uses_mtime_when_meta_absent(self, cache: SkillsIndexCache) -> None:
        cache.save_index([_item("a", "Alpha")])
        assert cache.is_cache_valid() is True

    def test_expired_mtime_invalid(self, cache: SkillsIndexCache) -> None:
        cache.save_index([_item("a", "Alpha")])
        stale = time.time() - 7200
        (cache.cache_dir / "skills-index.json").touch()
        import os

        os.utime(cache.cache_dir / "skills-index.json", (stale, stale))
        assert cache.is_cache_valid() is False

    def test_meta_timestamp_drives_validity(self, cache: SkillsIndexCache) -> None:
        cache.save_index([_item("a", "Alpha")], etag="etag-9")
        assert cache.is_cache_valid() is True
        (cache.cache_dir / "skills-index.meta.json").write_text(
            json.dumps({"etag": "etag-9", "timestamp": time.time() - 7200}), encoding="utf-8"
        )
        assert cache.is_cache_valid() is False

    def test_corrupt_meta_invalid(self, cache: SkillsIndexCache) -> None:
        cache.save_index([_item("a", "Alpha")], etag="etag-9")
        (cache.cache_dir / "skills-index.meta.json").write_text("{not json", encoding="utf-8")
        assert cache.is_cache_valid() is False


class TestSearchInMemory:
    @pytest.fixture
    def loaded(self, cache: SkillsIndexCache) -> SkillsIndexCache:
        cache.save_index(
            [
                _item("a/pdf-tools", "pdf-tools", description="extract text", tags=["pdf"], stars=500),
                _item("b/image-kit", "image-kit", description="resize", tags=["image"], stars=10),
                _item("c/other", "other", description="unrelated", keywords=["pdf"]),
            ]
        )
        cache.load_cached_index()
        return cache

    def test_blank_query_returns_everything(self, loaded: SkillsIndexCache) -> None:
        assert len(loaded.search_in_memory("   ")) == 3

    def test_blank_query_respects_limit(self, loaded: SkillsIndexCache) -> None:
        assert len(loaded.search_in_memory("", limit=2)) == 2

    def test_exact_name_scores_highest(self, loaded: SkillsIndexCache) -> None:
        results = loaded.search_in_memory("pdf-tools")
        assert results[0].id == "a/pdf-tools"

    def test_matches_description(self, loaded: SkillsIndexCache) -> None:
        assert [r.id for r in loaded.search_in_memory("resize")] == ["b/image-kit"]

    def test_matches_keyword(self, loaded: SkillsIndexCache) -> None:
        assert "c/other" in [r.id for r in loaded.search_in_memory("pdf")]

    def test_all_tokens_must_match(self, loaded: SkillsIndexCache) -> None:
        assert loaded.search_in_memory("pdf resize") == []

    def test_unmatched_query_returns_empty(self, loaded: SkillsIndexCache) -> None:
        assert loaded.search_in_memory("absent") == []

    def test_regex_metacharacters_are_escaped(self, loaded: SkillsIndexCache) -> None:
        assert loaded.search_in_memory(".*") == []

    def test_limit_truncates(self, loaded: SkillsIndexCache) -> None:
        assert len(loaded.search_in_memory("pdf image", limit=1)) <= 1

    def test_lazily_loads_from_disk(self, cache: SkillsIndexCache) -> None:
        cache.save_index([_item("a", "Alpha")])
        fresh = SkillsIndexCache(cache_dir=cache.cache_dir, ttl_seconds=3600)
        assert len(fresh.search_in_memory("alpha")) == 1
