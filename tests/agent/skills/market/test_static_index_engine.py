"""Unit tests for the static skills index mirror engine and its models.

[INPUT]
- myrm_agent_harness.agent.skills.market.static_index

[OUTPUT]
- pytest suite covering local cache round-trips, ETag conditional sync,
  gzip payloads, in-memory ranking, and the index data models.

[POS]
myrm-agent-harness/tests/agent/skills/market/test_static_index_engine.py
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import httpx
import pytest
import respx

from myrm_agent_harness.agent.skills.market.static_index import (
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_STATIC_INDEX_URL,
    StaticIndexManifest,
    StaticSkillItem,
    StaticSkillsIndexManager,
)

INDEX_URL = "https://cdn.test/skills-index.json.gz"


def _item_dict(
    skill_id: str,
    name: str,
    *,
    description: str = "desc",
    source: str = "clawhub",
    stars: int = 0,
    downloads: int = 0,
    tags: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": skill_id,
        "name": name,
        "description": description,
        "source": source,
        "stars": stars,
        "downloads": downloads,
        "tags": tags or [],
    }


def _index_payload(*items: dict[str, object]) -> str:
    return json.dumps({"version": "2.0", "updated_at": "2026-01-01", "skills": list(items)})


@pytest.fixture
def manager(tmp_path: Path) -> StaticSkillsIndexManager:
    return StaticSkillsIndexManager(index_url=INDEX_URL, cache_dir=tmp_path, ttl_seconds=3600)


class TestModels:
    def test_item_round_trips_through_dict(self) -> None:
        item = StaticSkillItem(id="a", name="Alpha", description="d", tags=["x"], stars=3)
        assert StaticSkillItem.from_dict(item.to_dict()) == item

    def test_from_dict_applies_defaults(self) -> None:
        item = StaticSkillItem.from_dict({"id": "a", "name": "Alpha", "description": "d"})
        assert item.source == "clawhub"
        assert item.version == "1.0.0"
        assert item.stars == 0
        assert item.tags == []
        assert item.verified is True

    def test_from_dict_coerces_types(self) -> None:
        item = StaticSkillItem.from_dict(
            {"id": 1, "name": 2, "description": 3, "stars": "7", "downloads": "9", "verified": 0}
        )
        assert item.id == "1"
        assert item.stars == 7
        assert item.downloads == 9
        assert item.verified is False

    def test_manifest_defaults(self) -> None:
        manifest = StaticIndexManifest()
        assert manifest.version == "1.0"
        assert manifest.skills == []


class TestModuleDefaults:
    def test_exported_defaults(self) -> None:
        assert DEFAULT_STATIC_INDEX_URL.endswith("skills-index.json.gz")
        assert DEFAULT_CACHE_TTL_SECONDS == 6 * 3600


class TestLocalCache:
    def test_missing_cache_returns_false(self, manager: StaticSkillsIndexManager) -> None:
        assert manager.load_local_cache() is False

    def test_save_then_load_round_trip(self, manager: StaticSkillsIndexManager) -> None:
        payload = _index_payload(_item_dict("a", "Alpha"), _item_dict("b", "Beta"))
        manager.save_local_cache(payload, etag='W/"v1"')

        fresh = StaticSkillsIndexManager(index_url=INDEX_URL, cache_dir=manager.cache_dir)
        assert fresh.load_local_cache() is True
        assert fresh.total_skills == 2
        assert fresh.get_skill("a").name == "Alpha"
        assert fresh._manifest.version == "2.0"

    def test_load_restores_etag(self, manager: StaticSkillsIndexManager) -> None:
        manager.save_local_cache(_index_payload(_item_dict("a", "Alpha")), etag="etag-1")
        fresh = StaticSkillsIndexManager(index_url=INDEX_URL, cache_dir=manager.cache_dir)
        fresh.load_local_cache()
        assert fresh._etag == "etag-1"

    def test_load_without_etag_file(self, manager: StaticSkillsIndexManager) -> None:
        manager.save_local_cache(_index_payload(_item_dict("a", "Alpha")))
        fresh = StaticSkillsIndexManager(index_url=INDEX_URL, cache_dir=manager.cache_dir)
        assert fresh.load_local_cache() is True
        assert fresh._etag == ""

    def test_corrupt_cache_returns_false(self, manager: StaticSkillsIndexManager) -> None:
        manager.get_cache_file_path().write_text("{not json", encoding="utf-8")
        assert manager.load_local_cache() is False

    def test_save_failure_is_swallowed(self, manager: StaticSkillsIndexManager) -> None:
        blocked = manager.cache_dir / "blocked"
        blocked.write_text("i am a file", encoding="utf-8")
        manager.cache_dir = blocked
        manager.save_local_cache("{}")
        assert manager.get_cache_file_path().parent == blocked

    def test_cache_paths_live_in_cache_dir(self, manager: StaticSkillsIndexManager) -> None:
        assert manager.get_cache_file_path().parent == manager.cache_dir
        assert manager.get_etag_file_path().parent == manager.cache_dir


class TestSyncRemoteIndex:
    @pytest.mark.asyncio
    @respx.mock
    async def test_syncs_plain_json(self, manager: StaticSkillsIndexManager) -> None:
        respx.get(INDEX_URL).mock(
            return_value=httpx.Response(
                200,
                text=_index_payload(_item_dict("a", "Alpha")),
                headers={"ETag": 'W/"v2"'},
            )
        )
        assert await manager.sync_remote_index() is True
        assert manager.total_skills == 1
        assert manager._etag == 'W/"v2"'

    @pytest.mark.asyncio
    @respx.mock
    async def test_syncs_gzip_payload(self, manager: StaticSkillsIndexManager) -> None:
        body = gzip.compress(_index_payload(_item_dict("a", "Alpha"), _item_dict("b", "Beta")).encode())
        respx.get(INDEX_URL).mock(return_value=httpx.Response(200, content=body))

        assert await manager.sync_remote_index() is True
        assert manager.total_skills == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_not_modified_keeps_cache(self, manager: StaticSkillsIndexManager) -> None:
        manager.save_local_cache(_index_payload(_item_dict("a", "Alpha")), etag="etag-1")
        manager.load_local_cache()
        # 304 分支只在缓存已过期但仍持有 ETag 时可达
        manager._last_sync_time = 0.0
        route = respx.get(INDEX_URL).mock(return_value=httpx.Response(304))

        assert await manager.sync_remote_index() is True
        assert route.calls.last.request.headers["If-None-Match"] == "etag-1"
        assert manager.total_skills == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_force_omits_conditional_header(self, manager: StaticSkillsIndexManager) -> None:
        manager.save_local_cache(_index_payload(_item_dict("a", "Alpha")), etag="etag-1")
        manager.load_local_cache()
        route = respx.get(INDEX_URL).mock(return_value=httpx.Response(304))

        await manager.sync_remote_index(force=True)
        assert "If-None-Match" not in route.calls.last.request.headers
        assert manager.total_skills == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_fresh_cache_short_circuits(self, manager: StaticSkillsIndexManager) -> None:
        manager.save_local_cache(_index_payload(_item_dict("a", "Alpha")))
        manager.load_local_cache()
        route = respx.get(INDEX_URL)

        assert await manager.sync_remote_index() is True
        assert not route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_error_status_returns_false(self, manager: StaticSkillsIndexManager) -> None:
        respx.get(INDEX_URL).mock(return_value=httpx.Response(500))
        assert await manager.sync_remote_index() is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_network_error_returns_false(self, manager: StaticSkillsIndexManager) -> None:
        respx.get(INDEX_URL).mock(side_effect=httpx.TimeoutException("slow"))
        assert await manager.sync_remote_index() is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_malformed_json_returns_false(self, manager: StaticSkillsIndexManager) -> None:
        respx.get(INDEX_URL).mock(return_value=httpx.Response(200, text="{not json"))
        assert await manager.sync_remote_index() is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_stale_flag_tracks_sync_time(self, manager: StaticSkillsIndexManager) -> None:
        respx.get(INDEX_URL).mock(return_value=httpx.Response(200, text=_index_payload()))
        assert manager.is_stale is True
        await manager.sync_remote_index()
        assert manager.is_stale is False


class TestSearch:
    @pytest.fixture
    def loaded(self, manager: StaticSkillsIndexManager) -> StaticSkillsIndexManager:
        manager._skills_map = {
            "a/pdf-tools": StaticSkillItem(
                id="a/pdf-tools",
                name="pdf-tools",
                description="extract text from pdf",
                source="clawhub",
                stars=500,
                downloads=9000,
                tags=["pdf", "text"],
            ),
            "b/image-kit": StaticSkillItem(
                id="b/image-kit",
                name="image-kit",
                description="resize pictures",
                source="lobehub",
                stars=10,
                downloads=100,
                tags=["image"],
            ),
        }
        return manager

    def test_browse_sorts_by_popularity(self, loaded: StaticSkillsIndexManager) -> None:
        results = loaded.search("", limit=10)
        assert [r.id for r in results] == ["a/pdf-tools", "b/image-kit"]

    def test_browse_respects_limit(self, loaded: StaticSkillsIndexManager) -> None:
        assert len(loaded.search("", limit=1)) == 1

    def test_matches_name_prefix(self, loaded: StaticSkillsIndexManager) -> None:
        assert [r.id for r in loaded.search("pdf")] == ["a/pdf-tools"]

    def test_matches_id(self, loaded: StaticSkillsIndexManager) -> None:
        assert [r.id for r in loaded.search("image-kit")] == ["b/image-kit"]

    def test_matches_description(self, loaded: StaticSkillsIndexManager) -> None:
        assert [r.id for r in loaded.search("pictures")] == ["b/image-kit"]

    def test_matches_tag(self, loaded: StaticSkillsIndexManager) -> None:
        assert [r.id for r in loaded.search("pdf")] == ["a/pdf-tools"]

    def test_all_terms_must_match(self, loaded: StaticSkillsIndexManager) -> None:
        assert loaded.search("pdf resize") == []

    def test_source_filter(self, loaded: StaticSkillsIndexManager) -> None:
        assert [r.id for r in loaded.search("", source_filter="lobehub")] == ["b/image-kit"]

    def test_tag_filter(self, loaded: StaticSkillsIndexManager) -> None:
        assert [r.id for r in loaded.search("", tag_filter="image")] == ["b/image-kit"]

    def test_tag_filter_excludes(self, loaded: StaticSkillsIndexManager) -> None:
        assert loaded.search("", tag_filter="absent") == []

    def test_case_insensitive_query(self, loaded: StaticSkillsIndexManager) -> None:
        assert len(loaded.search("PDF")) == 1

    def test_results_carry_install_metadata(self, loaded: StaticSkillsIndexManager) -> None:
        result = loaded.search("pdf")[0]
        assert result.install_method == "zip"
        assert result.source == "clawhub"
        assert result.stars == 500

    def test_get_skill_miss_returns_none(self, loaded: StaticSkillsIndexManager) -> None:
        assert loaded.get_skill("absent") is None
