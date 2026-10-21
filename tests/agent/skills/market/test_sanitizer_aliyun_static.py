"""Unit tests for the sanitizer, Aliyun source, and static index source.

[INPUT]
- myrm_agent_harness.agent.skills.market.sanitizer
- myrm_agent_harness.agent.skills.market.sources.aliyun
- myrm_agent_harness.agent.skills.market.sources.static_index

[OUTPUT]
- pytest suite covering blocked-path filtering, size limits, Aliyun
  credential gating and response mapping, and the static index source's
  disk cache, mirror fallback, and relevance scoring. No network calls.

[POS]
myrm-agent-harness/tests/agent/skills/market/test_sanitizer_aliyun_static.py
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from myrm_agent_harness.agent.skills.market.sanitizer import (
    MAX_SINGLE_FILE_SIZE,
    MAX_TOTAL_UPLOAD_SIZE,
    is_blocked_file,
    sanitize_skill_files,
)
from myrm_agent_harness.agent.skills.market.sources.aliyun import (
    AliyunSource,
    _extract_skill_items,
    _opt_int,
    _str,
    _to_search_result,
    _unwrap,
)
from myrm_agent_harness.agent.skills.market.sources.static_index import (
    DEFAULT_MIRROR_URLS,
    StaticIndexSkillSource,
)

INDEX_URL = "https://index.test/skills-index.json.gz"


class TestIsBlockedFile:
    @pytest.mark.parametrize(
        "path",
        [
            ".git/config",
            "sub/.git/HEAD",
            "pkg.egg-info/PKG-INFO",
            "dir/venv/file.txt",
            ".env",
            "a/__pycache__/x.pyc",
            "a/dist/out.js",
            "a/desktop.ini",
            "win\\desktop.ini",
            "x/.npmrc",
        ],
    )
    def test_blocked(self, path: str) -> None:
        assert is_blocked_file(path) is True

    @pytest.mark.parametrize(
        "path",
        ["SKILL.md", "scripts/run.py", "docs/guide.md", "src/a/b.py"],
    )
    def test_allowed(self, path: str) -> None:
        assert is_blocked_file(path) is False


class TestSanitizeSkillFiles:
    def test_keeps_valid_files(self) -> None:
        files = {"SKILL.md": b"# a", "scripts/run.py": b"print(1)"}
        assert sanitize_skill_files(files) == files

    def test_drops_blocked_files(self) -> None:
        files = {"SKILL.md": b"# a", ".env": b"SECRET=1"}
        assert set(sanitize_skill_files(files)) == {"SKILL.md"}

    def test_raises_when_everything_filtered(self) -> None:
        with pytest.raises(ValueError, match="No valid files after filtering"):
            sanitize_skill_files({".env": b"x"})

    def test_raises_on_oversized_single_file(self) -> None:
        with pytest.raises(ValueError, match="exceeds size limit"):
            sanitize_skill_files({"SKILL.md": b"x" * (MAX_SINGLE_FILE_SIZE + 1)})

    def test_raises_on_oversized_total(self) -> None:
        chunk = b"x" * (MAX_SINGLE_FILE_SIZE - 1)
        files = {f"f{i}.md": chunk for i in range(6)}
        with pytest.raises(ValueError, match="Total upload size exceeds limit"):
            sanitize_skill_files(files)

    def test_total_under_limit_is_accepted(self) -> None:
        assert len(sanitize_skill_files({"SKILL.md": b"a" * 1024})) == 1
        assert MAX_TOTAL_UPLOAD_SIZE > MAX_SINGLE_FILE_SIZE


def _aliyun_item(**kwargs: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "skillName": "pdf",
        "displayName": "PDF Kit",
        "description": "d",
        "provider": "acme",
        "version": "1.0.0",
        "installCount": "12",
        "likeCount": 3,
        "categoryName": "docs",
        "subCategoryName": "docs",
    }
    payload.update(kwargs)
    return payload


class TestAliyunHelpers:
    def test_str_coerces_and_strips(self) -> None:
        assert _str("  a  ") == "a"
        assert _str(3) == ""
        assert _str(None) == ""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(5, 5), ("7", 7), (True, None), (False, None), ("x", None), (None, None), (1.5, None)],
    )
    def test_opt_int(self, value: Any, expected: int | None) -> None:
        assert _opt_int(value) == expected

    def test_unwrap_reads_body(self) -> None:
        assert _unwrap({"body": {"a": 1}}) == {"a": 1}
        assert _unwrap({"a": 1}) == {"a": 1}

    def test_extract_items_from_data(self) -> None:
        assert _extract_skill_items({"data": [{"a": 1}, "junk"]}) == [{"a": 1}]

    @pytest.mark.parametrize("body", [{}, {"data": "nope"}, ["x"], None])
    def test_extract_items_rejects_other_shapes(self, body: Any) -> None:
        assert _extract_skill_items(body) == []

    def test_to_search_result_maps_fields(self) -> None:
        result = _to_search_result(_aliyun_item(subCategoryName="convert"))
        assert result.id == "pdf"
        assert result.name == "PDF Kit"
        assert result.author == "acme"
        assert result.downloads == 12
        assert result.stars == 3
        assert result.tags == ["docs", "convert"]
        assert result.install_method == "direct"
        assert result.readme_url == result.install_url

    def test_to_search_result_requires_a_name(self) -> None:
        assert _to_search_result({}) is None

    def test_to_search_result_falls_back_to_skill_name(self) -> None:
        result = _to_search_result({"skillName": "pdf", "owner": "bob"})
        assert result.name == "pdf"
        assert result.author == "bob"

    def test_to_search_result_url_encodes(self) -> None:
        result = _to_search_result({"skillName": "a/b"})
        assert "%2F" in result.install_url

    def test_to_search_result_defaults_counts(self) -> None:
        result = _to_search_result({"skillName": "pdf"})
        assert result.downloads == 0
        assert result.stars == 0
        assert result.tags == []


class TestAliyunSource:
    def test_source_name(self) -> None:
        assert AliyunSource().source_name == "aliyun"

    @pytest.mark.asyncio
    async def test_search_without_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", raising=False)
        assert await AliyunSource().search("pdf") == []

    @pytest.mark.asyncio
    async def test_get_detail_without_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", raising=False)
        assert await AliyunSource().get_detail("pdf") is None

    @pytest.mark.asyncio
    async def test_search_maps_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_credentials(monkeypatch)
        source = AliyunSource()
        source._call_api = AsyncMock(  # type: ignore[method-assign]
            return_value={"data": [_aliyun_item(), {"nope": 1}]}
        )
        results = await source.search(" pdf ")
        assert [r.id for r in results] == ["pdf"]
        assert source._call_api.await_args.kwargs["query"] == {"maxResults": 10, "keyword": "pdf"}

    @pytest.mark.asyncio
    async def test_search_clamps_page_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_credentials(monkeypatch)
        source = AliyunSource()
        source._call_api = AsyncMock(return_value={})  # type: ignore[method-assign]
        await source.search("", limit=10_000)
        assert source._call_api.await_args.kwargs["query"] == {"maxResults": 100}

    @pytest.mark.asyncio
    async def test_search_handles_blank_keyword(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_credentials(monkeypatch)
        source = AliyunSource()
        source._call_api = AsyncMock(return_value={})  # type: ignore[method-assign]
        await source.search("   ", limit=1)
        assert source._call_api.await_args.kwargs["query"] == {"maxResults": 1}

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_credentials(monkeypatch)
        source = AliyunSource()
        source._call_api = AsyncMock(  # type: ignore[method-assign]
            return_value={"data": [_aliyun_item(skillName="a"), _aliyun_item(skillName="b")]}
        )
        assert len(await source.search("x", limit=1)) == 1

    @pytest.mark.asyncio
    async def test_search_swallows_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_credentials(monkeypatch)
        source = AliyunSource()
        source._call_api = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
        assert await source.search("pdf") == []

    @pytest.mark.asyncio
    async def test_get_detail_maps_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_credentials(monkeypatch)
        source = AliyunSource()
        source._call_api = AsyncMock(return_value=_aliyun_item())  # type: ignore[method-assign]
        result = await source.get_detail("pdf")
        assert result is not None
        assert result.id == "pdf"

    @pytest.mark.asyncio
    async def test_get_detail_rejects_non_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_credentials(monkeypatch)
        source = AliyunSource()
        source._call_api = AsyncMock(return_value=["nope"])  # type: ignore[method-assign]
        assert await source.get_detail("pdf") is None

    @pytest.mark.asyncio
    async def test_get_detail_swallows_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _with_credentials(monkeypatch)
        source = AliyunSource()
        source._call_api = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
        assert await source.get_detail("pdf") is None

    @pytest.mark.asyncio
    async def test_call_api_signs_request_via_sdk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_sdk(monkeypatch)
        assert await AliyunSource()._call_api(
            action="SearchSkills", pathname="/openapi/skills", query={"a": 1, "b": None}
        ) == {"ok": True}

    @pytest.mark.asyncio
    async def test_call_api_reports_missing_sdk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins

        real_import = builtins.__import__

        def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name.startswith("alibabacloud"):
                raise ImportError("no sdk")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)
        with pytest.raises(ImportError):
            await AliyunSource()._call_api(action="A", pathname="/p")


def _install_fake_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide minimal stand-ins for the alibabacloud SDK modules used by _call_api."""
    import sys
    import types

    captured: dict[str, Any] = {}

    class _Models(types.ModuleType):
        class Config:
            def __init__(self, credential: object = None) -> None:
                self.credential = credential

        class Params:
            def __init__(self, **kwargs: Any) -> None:
                self.__dict__.update(kwargs)

        class OpenApiRequest:
            def __init__(self, query: dict[str, str]) -> None:
                self.query = query

    class _Client:
        def __init__(self, config: object = None) -> None:
            captured["config"] = config

        async def do_request_async(self, params: object, request: object, runtime: object) -> dict[str, Any]:
            captured["params"] = params
            captured["request"] = request
            captured["runtime"] = runtime
            return {"body": {"ok": True}}

    class _Runtime:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    models = _Models("alibabacloud_tea_openapi.models")
    models.Config = _Models.Config  # type: ignore[attr-defined]
    models.Params = _Models.Params  # type: ignore[attr-defined]
    models.OpenApiRequest = _Models.OpenApiRequest  # type: ignore[attr-defined]

    creds = types.ModuleType("alibabacloud_credentials.client")
    creds.Client = lambda *a, **k: object()  # type: ignore[attr-defined]

    openapi = types.ModuleType("alibabacloud_tea_openapi")
    openapi.models = models  # type: ignore[attr-defined]
    openapi_client = types.ModuleType("alibabacloud_tea_openapi.client")
    openapi_client.Client = _Client  # type: ignore[attr-defined]

    util = types.ModuleType("alibabacloud_tea_util")
    util_models = types.ModuleType("alibabacloud_tea_util.models")
    util_models.RuntimeOptions = _Runtime  # type: ignore[attr-defined]
    util.models = util_models  # type: ignore[attr-defined]

    for name, module in {
        "alibabacloud_credentials": types.ModuleType("alibabacloud_credentials"),
        "alibabacloud_credentials.client": creds,
        "alibabacloud_tea_openapi": openapi,
        "alibabacloud_tea_openapi.models": models,
        "alibabacloud_tea_openapi.client": openapi_client,
        "alibabacloud_tea_util": util,
        "alibabacloud_tea_util.models": util_models,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(_Client, "captured", captured, raising=False)


def _with_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "id")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "secret")


def _source(tmp_path: Path, **kwargs: Any) -> StaticIndexSkillSource:
    return StaticIndexSkillSource(index_url=INDEX_URL, cache_dir=tmp_path, ttl_seconds=3600, **kwargs)


def _index(*items: dict[str, Any]) -> str:
    return json.dumps({"skills": list(items)})


class TestStaticIndexEdgeCases:
    @pytest.mark.asyncio
    async def test_etag_read_failure_is_ignored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        etag_file = tmp_path / "skills-index.etag"
        etag_file.write_text("W/1", encoding="utf-8")
        source = _source(tmp_path)
        monkeypatch.setattr(Path, "read_text", _raise_os_error)
        with respx.mock:
            respx.get(INDEX_URL).mock(return_value=httpx.Response(304))
            assert await source._sync_remote_index(force=False) is True

    @pytest.mark.asyncio
    async def test_blank_etag_sends_no_conditional_header(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "skills-index.etag").write_text("   ", encoding="utf-8")
        source = _source(tmp_path)
        source._index_url = ""
        with respx.mock:
            route = respx.get(DEFAULT_MIRROR_URLS[0]).mock(return_value=httpx.Response(304))
            assert await source._sync_remote_index(force=False) is True
        assert "If-None-Match" not in route.calls.last.request.headers

    @pytest.mark.asyncio
    async def test_loaded_and_fresh_index_skips_all_io(self, tmp_path: Path) -> None:
        source = _source(tmp_path, preloaded_entries=[{"id": "a", "name": "A"}])
        source._is_loaded = True
        source._last_synced_at = 9_999_999_999.0
        with respx.mock:
            for url in (INDEX_URL, *DEFAULT_MIRROR_URLS):
                respx.get(url)
            assert len(await source.search("")) == 1

    @pytest.mark.asyncio
    async def test_no_candidate_urls_returns_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        source = _source(tmp_path)
        source._index_url = ""
        monkeypatch.setattr("myrm_agent_harness.agent.skills.market.sources.static_index.DEFAULT_MIRROR_URLS", ())
        assert await source._sync_remote_index(force=True) is False


class TestStaticIndexPreloaded:
    def test_source_name_and_count(self) -> None:
        source = _source(Path("/tmp/unused-1"), preloaded_entries=[{"id": "a", "name": "A"}])
        assert source.source_name == "static_index"
        assert source.total_indexed_skills == 1

    def test_entry_defaults(self) -> None:
        source = _source(Path("/tmp/unused-2"), preloaded_entries=[{}])
        entry = source._entries[0]
        assert entry.id == "unknown"
        assert entry.name == "Unnamed"
        assert entry.source == "static_index"
        assert entry.author == "community"
        assert entry.install_method == "git"
        assert entry.package_type == "skill"
        assert entry.version == "1.0.0"

    def test_entry_accepts_valid_enums(self) -> None:
        source = _source(
            Path("/tmp/unused-3"),
            preloaded_entries=[
                {
                    "id": "a",
                    "install_method": "zip",
                    "package_type": "agent_plugin",
                    "subdirectory": "s",
                    "extra_manifest": {"k": 1},
                }
            ],
        )
        entry = source._entries[0]
        assert entry.install_method == "zip"
        assert entry.package_type == "agent_plugin"
        assert entry.subdirectory == "s"
        assert entry.extra_manifest == {"k": 1}

    def test_entry_rejects_invalid_enums(self) -> None:
        source = _source(
            Path("/tmp/unused-4"),
            preloaded_entries=[{"id": "a", "install_method": "svn", "package_type": "weird"}],
        )
        entry = source._entries[0]
        assert entry.install_method == "git"
        assert entry.package_type == "skill"

    def test_malformed_entry_is_skipped(self) -> None:
        source = _source(Path("/tmp/unused-5"), preloaded_entries=[{"id": "a", "stars": "not-int"}])
        assert source._entries == []

    def test_id_falls_back_to_name(self) -> None:
        source = _source(Path("/tmp/unused-6"), preloaded_entries=[{"name": "only-name"}])
        assert source._entries[0].id == "only-name"


class TestStaticIndexSearch:
    @pytest.fixture
    def loaded(self, tmp_path: Path) -> StaticIndexSkillSource:
        return _source(
            tmp_path,
            preloaded_entries=[
                {"id": "a/pdf", "name": "PDF Kit", "description": "extract text", "tags": ["docs"]},
                {"id": "b/img", "name": "Image Kit", "description": "resize", "stars": 50},
            ],
        )

    @pytest.mark.asyncio
    async def test_blank_query_returns_all(self, loaded: StaticIndexSkillSource) -> None:
        assert len(await loaded.search("  ")) == 2

    @pytest.mark.asyncio
    async def test_blank_query_respects_limit(self, loaded: StaticIndexSkillSource) -> None:
        assert len(await loaded.search("", limit=1)) == 1

    @pytest.mark.asyncio
    async def test_matches_name_and_desc(self, loaded: StaticIndexSkillSource) -> None:
        assert [r.id for r in await loaded.search("pdf")] == ["a/pdf"]
        assert [r.id for r in await loaded.search("resize")] == ["b/img"]

    @pytest.mark.asyncio
    async def test_exact_name_outranks_partial(self, tmp_path: Path) -> None:
        source = _source(
            tmp_path,
            preloaded_entries=[
                {"id": "a", "name": "pdf helper", "description": ""},
                {"id": "b", "name": "pdf", "description": ""},
            ],
        )
        assert (await source.search("pdf"))[0].id == "b"

    @pytest.mark.asyncio
    async def test_unmatched_query_returns_empty(self, loaded: StaticIndexSkillSource) -> None:
        assert await loaded.search("absent") == []

    @pytest.mark.asyncio
    async def test_get_detail_matches_id_or_name(self, loaded: StaticIndexSkillSource) -> None:
        assert (await loaded.get_detail("A/PDF")).id == "a/pdf"
        assert (await loaded.get_detail("image kit")).id == "b/img"
        assert await loaded.get_detail("absent") is None

    @pytest.mark.asyncio
    async def test_relevance_includes_tags_and_keywords(self) -> None:
        from myrm_agent_harness.backends.skills.market_protocols import SkillSearchResult

        item = SkillSearchResult(
            id="a",
            name="n",
            description="d",
            source="static_index",
            author="a",
            install_url="u",
            install_method="git",
            tags=["Alpha"],
            keywords=["beta"],
        )
        assert StaticIndexSkillSource._compute_relevance(item, "alpha", ["alpha"]) > 0
        assert StaticIndexSkillSource._compute_relevance(item, "beta", ["beta"]) > 0
        assert StaticIndexSkillSource._compute_relevance(item, "zzz", ["zzz"]) == 0.0


class TestStaticIndexCacheAndSync:
    @pytest.mark.asyncio
    @respx.mock
    async def test_syncs_gzip_and_persists_cache(self, tmp_path: Path) -> None:
        body = gzip.compress(_index({"id": "a", "name": "A"}).encode())
        route = respx.get(INDEX_URL).mock(return_value=httpx.Response(200, content=body, headers={"etag": "W/1"}))
        source = _source(tmp_path)

        assert await source.force_refresh() is True
        assert route.called
        assert source.total_indexed_skills == 1
        assert (tmp_path / "skills-index.json.gz").exists()
        assert (tmp_path / "skills-index.etag").read_text(encoding="utf-8") == "W/1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_syncs_plain_json(self, tmp_path: Path) -> None:
        respx.get(INDEX_URL).mock(return_value=httpx.Response(200, content=_index({"id": "a", "name": "A"}).encode()))
        source = _source(tmp_path)
        assert await source.force_refresh() is True
        assert source.total_indexed_skills == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_accepts_bare_list_payload(self, tmp_path: Path) -> None:
        respx.get(INDEX_URL).mock(
            return_value=httpx.Response(200, content=json.dumps([{"id": "a", "name": "A"}]).encode())
        )
        assert await _source(tmp_path).force_refresh() is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_unrecognized_payload_keeps_local_mirror(self, tmp_path: Path) -> None:
        """缺少 skills/items 键的响应不可采纳，否则坏载荷会清空本地镜像。"""
        for url in (INDEX_URL, *DEFAULT_MIRROR_URLS):
            respx.get(url).mock(return_value=httpx.Response(200, content=json.dumps({"nope": 1}).encode()))
        source = _source(tmp_path, preloaded_entries=[{"id": "a", "name": "A"}])
        assert await source.force_refresh() is False
        assert source.total_indexed_skills == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_wrong_items_type_keeps_local_mirror(self, tmp_path: Path) -> None:
        for url in (INDEX_URL, *DEFAULT_MIRROR_URLS):
            respx.get(url).mock(return_value=httpx.Response(200, content=json.dumps({"skills": "nope"}).encode()))
        source = _source(tmp_path, preloaded_entries=[{"id": "a", "name": "A"}])
        assert await source.force_refresh() is False
        assert source.total_indexed_skills == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_explicit_empty_index_is_accepted(self, tmp_path: Path) -> None:
        """显式声明 skills: [] 视为合法空索引。"""
        for url in (INDEX_URL, *DEFAULT_MIRROR_URLS):
            respx.get(url).mock(return_value=httpx.Response(200, content=json.dumps({"skills": []}).encode()))
        source = _source(tmp_path, preloaded_entries=[{"id": "a", "name": "A"}])
        assert await source.force_refresh() is True
        assert source.total_indexed_skills == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_non_200_skips_mirror_chain(self, tmp_path: Path) -> None:
        for url in (INDEX_URL, *DEFAULT_MIRROR_URLS):
            respx.get(url).mock(return_value=httpx.Response(500))
        assert await _source(tmp_path).force_refresh() is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_falls_back_to_mirror(self, tmp_path: Path) -> None:
        respx.get(INDEX_URL).mock(side_effect=httpx.ConnectError("down"))
        mirror = respx.get(DEFAULT_MIRROR_URLS[1]).mock(
            return_value=httpx.Response(200, content=_index({"id": "a", "name": "A"}).encode())
        )
        assert await _source(tmp_path).force_refresh() is True
        assert mirror.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_all_mirrors_fail(self, tmp_path: Path) -> None:
        for url in (INDEX_URL, *DEFAULT_MIRROR_URLS):
            respx.get(url).mock(side_effect=httpx.ConnectError("down"))
        source = _source(tmp_path)
        assert await source.force_refresh() is False
        # 失败后仍记录时间戳，避免立即重试
        assert source._last_synced_at > 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_304_keeps_existing_entries(self, tmp_path: Path) -> None:
        source = _source(tmp_path, preloaded_entries=[{"id": "a", "name": "A"}])
        respx.get(INDEX_URL).mock(return_value=httpx.Response(304))
        assert await source.force_refresh() is True
        assert source.total_indexed_skills == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_etag_is_sent_when_not_forced(self, tmp_path: Path) -> None:
        (tmp_path / "skills-index.etag").write_text("W/9", encoding="utf-8")
        route = respx.get(INDEX_URL).mock(return_value=httpx.Response(304))
        source = _source(tmp_path)

        assert await source._sync_remote_index(force=False) is True
        assert route.calls.last.request.headers["If-None-Match"] == "W/9"

    @pytest.mark.asyncio
    @respx.mock
    async def test_304_reloads_disk_when_empty(self, tmp_path: Path) -> None:
        (tmp_path / "skills-index.json.gz").write_bytes(gzip.compress(_index({"id": "a", "name": "A"}).encode()))
        respx.get(INDEX_URL).mock(return_value=httpx.Response(304))
        source = _source(tmp_path)
        assert await source.force_refresh() is True
        assert source.total_indexed_skills == 1

    @pytest.mark.asyncio
    async def test_loads_uncompressed_disk_cache(self, tmp_path: Path) -> None:
        (tmp_path / "skills-index.json").write_text(_index({"id": "a", "name": "A"}), encoding="utf-8")
        source = _source(tmp_path)
        assert source._load_from_disk_cache() is True
        assert source.total_indexed_skills == 1

    @pytest.mark.asyncio
    async def test_loads_gzip_disk_cache(self, tmp_path: Path) -> None:
        (tmp_path / "skills-index.json.gz").write_bytes(gzip.compress(_index({"id": "a", "name": "A"}).encode()))
        source = _source(tmp_path)
        assert source._load_from_disk_cache() is True

    @pytest.mark.asyncio
    async def test_disk_cache_falls_back_to_plain_text(self, tmp_path: Path) -> None:
        (tmp_path / "skills-index.json.gz").write_text(_index({"id": "a", "name": "A"}), encoding="utf-8")
        assert _source(tmp_path)._load_from_disk_cache() is True

    @pytest.mark.asyncio
    async def test_corrupt_uncompressed_cache_returns_false(self, tmp_path: Path) -> None:
        (tmp_path / "skills-index.json").write_text("{not json", encoding="utf-8")
        assert _source(tmp_path)._load_from_disk_cache() is False

    @pytest.mark.asyncio
    async def test_corrupt_gzip_cache_returns_false(self, tmp_path: Path) -> None:
        (tmp_path / "skills-index.json.gz").write_bytes(b"\x1f\x8bbroken")
        assert _source(tmp_path)._load_from_disk_cache() is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_disk_write_failure_still_reports_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        respx.get(INDEX_URL).mock(return_value=httpx.Response(200, content=_index({"id": "a", "name": "A"}).encode()))
        source = _source(tmp_path)
        source._cache_dir = _ReadOnlyDir()  # type: ignore[assignment]
        monkeypatch.setattr(Path, "mkdir", _raise_os_error)

        assert await source.force_refresh() is True
        assert source.total_indexed_skills == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_uses_disk_cache_when_offline(self, tmp_path: Path) -> None:
        for url in (INDEX_URL, *DEFAULT_MIRROR_URLS):
            respx.get(url).mock(side_effect=httpx.ConnectError("down"))
        (tmp_path / "skills-index.json").write_text(_index({"id": "a", "name": "A"}), encoding="utf-8")
        source = _source(tmp_path)

        results = await source.search("")

        assert [r.id for r in results] == ["a"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_index_returns_nothing(self, tmp_path: Path) -> None:
        for url in (INDEX_URL, *DEFAULT_MIRROR_URLS):
            respx.get(url).mock(side_effect=httpx.ConnectError("down"))
        assert await _source(tmp_path).search("") == []


class _ReadOnlyDir:
    """Stand-in cache dir whose writes always fail."""

    def __truediv__(self, _other: object) -> Path:
        return Path("/proc/nonexistent/skills-index.json.gz")

    def mkdir(self, **_kwargs: Any) -> None:
        raise OSError("read-only")


def _raise_os_error(*_args: Any, **_kwargs: Any) -> None:
    raise OSError("read-only")
