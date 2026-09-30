"""Unit tests for skill market helpers and the LobeHub source.

[INPUT]
- myrm_agent_harness.agent.skills.market.helpers
- myrm_agent_harness.agent.skills.market.sources.lobehub

[OUTPUT]
- pytest suite covering multi-file scanning filters, dedup and ranking,
  origin provenance records, LobeHub agent conversion, and the LobeHub
  index cache. All HTTP is stubbed.

[POS]
myrm-agent-harness/tests/agent/skills/market/test_helpers_lobehub.py
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from myrm_agent_harness.agent.skills.market.helpers import (
    ORIGIN_FILENAME,
    SOURCE_PRIORITY,
    deduplicate,
    fetch_lobehub_as_skill,
    rank_results,
    read_origin,
    scan_all_text_files,
    write_origin,
)
from myrm_agent_harness.agent.skills.market.sources.lobehub import LobeHubSource
from myrm_agent_harness.backends.skills.market_protocols import SkillSearchResult


def _result(
    name: str,
    source: str = "github",
    *,
    stars: int = 0,
    description: str = "",
    tags: list[str] | None = None,
    keywords: list[str] | None = None,
) -> SkillSearchResult:
    return SkillSearchResult(
        id=f"{source}:{name}",
        name=name,
        description=description,
        source=source,
        author="a",
        install_url="u",
        install_method="git",
        stars=stars,
        tags=tags or [],
        keywords=keywords or [],
    )


class TestScanAllTextFiles:
    def test_scans_scannable_extensions(self) -> None:
        result = scan_all_text_files("s", {"a.md": b"hello", "b.py": b"x = 1"})
        assert result.skill_name == "s"

    def test_skips_non_scannable_extension(self) -> None:
        result = scan_all_text_files("s", {"a.png": b"binary"})
        assert result.findings == []
        assert result.ast_findings == []

    def test_skips_empty_files(self) -> None:
        assert scan_all_text_files("s", {"a.md": b""}).findings == []

    def test_skips_oversized_files(self) -> None:
        assert scan_all_text_files("s", {"a.md": b"x" * (512 * 1024 + 1)}).findings == []

    def test_skips_binary_content(self) -> None:
        assert scan_all_text_files("s", {"a.md": b"ok\x00bad"}).findings == []

    def test_skips_null_in_text_content(self) -> None:
        assert scan_all_text_files("s", {"a.md": "ok\x00bad"}).findings == []

    def test_skips_wrong_content_type(self) -> None:
        assert scan_all_text_files("s", {"a.md": 123}).findings == []  # type: ignore[dict-item]

    def test_merges_findings_across_files(self) -> None:
        result = scan_all_text_files("s", {"a.md": b"import os", "b.py": b"import socket"})
        assert result.skill_name == "s"

    def test_handles_empty_file_set(self) -> None:
        assert scan_all_text_files("s", {}).findings == []


class TestDeduplicate:
    def test_keeps_first_occurrence(self) -> None:
        first = _result("Alpha", "prebuilt")
        second = _result("Alpha", "github")
        assert deduplicate([first, second]) == [first]

    def test_is_case_insensitive(self) -> None:
        first = _result("Alpha")
        second = _result("ALPHA")
        assert deduplicate([first, second]) == [first]

    def test_keeps_distinct_names(self) -> None:
        results = [_result("A"), _result("B")]
        assert deduplicate(results) == results

    def test_empty_input(self) -> None:
        assert deduplicate([]) == []


class TestRankResults:
    def test_source_priority_dominates(self) -> None:
        low = _result("Same", "github", stars=500)
        high = _result("Same", "prebuilt")
        assert rank_results([low, high], "")[0].source == "prebuilt"

    def test_stars_break_ties(self) -> None:
        few = _result("A", "github", stars=1)
        many = _result("B", "github", stars=400)
        assert rank_results([few, many], "")[0].id == "github:B"

    def test_stars_are_capped(self) -> None:
        capped = _result("A", "github", stars=10_000)
        at_cap = _result("B", "github", stars=500)
        assert rank_results([capped, at_cap], "")[0].id in {"github:A", "github:B"}

    def test_name_match_outranks_stars(self) -> None:
        # 名称命中 +20 需超过 stars 权重（0.1/星）才能反超
        match = _result("pdf", "github")
        other = _result("other", "github", stars=100)
        assert rank_results([other, match], "pdf")[0].id == "github:pdf"

    def test_description_match_scores(self) -> None:
        match = _result("a", "github", description="handles pdf files")
        other = _result("b", "github")
        assert rank_results([other, match], "pdf")[0].id == "github:a"

    def test_keyword_and_tag_matches_score(self) -> None:
        tagged = _result("a", "github", tags=["pdf"])
        keyworded = _result("b", "github", keywords=["pdf"])
        plain = _result("c", "github")
        ranked = rank_results([plain, tagged, keyworded], "pdf")
        assert ranked[0].id == "github:b"
        assert ranked[1].id == "github:a"

    def test_priority_table_has_expected_tiers(self) -> None:
        assert SOURCE_PRIORITY["prebuilt"] > SOURCE_PRIORITY["static_index"]
        assert SOURCE_PRIORITY["clawhub"] > SOURCE_PRIORITY["github"]
        assert SOURCE_PRIORITY["lobehub"] < SOURCE_PRIORITY["github"]


class TestOrigin:
    def test_round_trip(self, tmp_path: Path) -> None:
        write_origin(tmp_path, source="github", skill_id="acme/pdf", version="1.0.0")
        origin = read_origin(tmp_path)
        assert origin["source"] == "github"
        assert origin["skill_id"] == "acme/pdf"
        assert origin["version"] == "1.0.0"
        assert "installed_at" in origin

    def test_optional_fields_are_omitted_when_absent(self, tmp_path: Path) -> None:
        write_origin(tmp_path, source="github", skill_id="a")
        origin = read_origin(tmp_path)
        assert "parent_plugin" not in origin
        assert "declared_mcp_servers" not in origin

    def test_optional_fields_are_persisted(self, tmp_path: Path) -> None:
        write_origin(
            tmp_path,
            source="github",
            skill_id="a",
            parent_plugin="suite",
            declared_mcp_servers=["fs"],
        )
        origin = read_origin(tmp_path)
        assert origin["parent_plugin"] == "suite"
        assert origin["declared_mcp_servers"] == ["fs"]

    def test_missing_origin_returns_empty(self, tmp_path: Path) -> None:
        assert read_origin(tmp_path) == {}

    def test_corrupt_origin_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / ORIGIN_FILENAME).write_text("{not json", encoding="utf-8")
        assert read_origin(tmp_path) == {}

    def test_write_failure_is_swallowed(self, tmp_path: Path) -> None:
        blocked = tmp_path / "blocked"
        blocked.write_text("file", encoding="utf-8")
        write_origin(blocked, source="github", skill_id="a")

    def test_origin_filename_constant(self) -> None:
        assert ORIGIN_FILENAME == "origin.json"


def _lobe_detail() -> SkillSearchResult:
    return SkillSearchResult(
        id="lobehub/agent",
        name="Agent",
        description="fallback description",
        source="lobehub",
        author="a",
        install_url="https://lobehub.com/api/agent/agent",
        install_method="direct",
    )


class TestFetchLobehubAsSkill:
    @pytest.mark.asyncio
    async def test_builds_skill_md(self) -> None:
        payload = {
            "meta": {"title": "Agent", "description": "does things", "tags": ["x", "y"]},
            "config": {"systemRole": "You are helpful."},
        }
        with patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new=AsyncMock(return_value=SimpleNamespace(status_code=200, json=lambda: payload)),
        ):
            files = await fetch_lobehub_as_skill(_lobe_detail())

        text = files["SKILL.md"].decode()
        assert "name: Agent" in text
        assert "tags: [x, y]" in text
        assert "## System Prompt" in text
        assert "You are helpful." in text

    @pytest.mark.asyncio
    async def test_without_system_role(self) -> None:
        payload = {"meta": {"title": "Agent", "description": "d", "tags": []}}
        with patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new=AsyncMock(return_value=SimpleNamespace(status_code=200, json=lambda: payload)),
        ):
            files = await fetch_lobehub_as_skill(_lobe_detail())

        text = files["SKILL.md"].decode()
        assert "tags: []" in text
        assert "System Prompt" not in text

    @pytest.mark.asyncio
    async def test_falls_back_to_detail_fields(self) -> None:
        with patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new=AsyncMock(return_value=SimpleNamespace(status_code=200, json=lambda: {})),
        ):
            files = await fetch_lobehub_as_skill(_lobe_detail())

        text = files["SKILL.md"].decode()
        assert "name: Agent" in text
        assert "description: fallback description" in text

    @pytest.mark.asyncio
    async def test_non_dict_meta_falls_back(self) -> None:
        payload = {"meta": "not a dict", "title": "Top"}
        with patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new=AsyncMock(return_value=SimpleNamespace(status_code=200, json=lambda: payload)),
        ):
            files = await fetch_lobehub_as_skill(_lobe_detail())
        assert b"name: Top" in files["SKILL.md"]

    @pytest.mark.asyncio
    async def test_non_200_raises(self) -> None:
        with (
            patch(
                "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
                new=AsyncMock(return_value=SimpleNamespace(status_code=502, json=lambda: {})),
            ),
            pytest.raises(ValueError, match="HTTP 502"),
        ):
            await fetch_lobehub_as_skill(_lobe_detail())

    @pytest.mark.asyncio
    async def test_oversized_payload_raises(self) -> None:
        from myrm_agent_harness.core.security.http.secure_fetch import ContentTooLargeError

        with (
            patch(
                "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
                new=AsyncMock(side_effect=ContentTooLargeError("too big")),
            ),
            pytest.raises(ValueError, match="too large"),
        ):
            await fetch_lobehub_as_skill(_lobe_detail())

    @pytest.mark.asyncio
    async def test_non_dict_body_raises(self) -> None:
        with (
            patch(
                "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
                new=AsyncMock(return_value=SimpleNamespace(status_code=200, json=lambda: ["nope"])),
            ),
            pytest.raises(ValueError, match="not a valid JSON object"),
        ):
            await fetch_lobehub_as_skill(_lobe_detail())


def _stub_client(status: int = 200, payload: object = None) -> MagicMock:
    client = MagicMock()
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload
    client.get = AsyncMock(return_value=response)
    client.is_closed = False
    return client


class TestLobeHubSource:
    def test_source_name(self) -> None:
        assert LobeHubSource().source_name == "lobehub"

    def test_client_is_reused_and_recreated(self) -> None:
        made: list[MagicMock] = []

        def _factory(**_kwargs: object) -> MagicMock:
            client = _stub_client()
            made.append(client)
            return client

        with patch("myrm_agent_harness.agent.skills.market.sources.lobehub.create_httpx_client", _factory):
            source = LobeHubSource()
            first = source._get_client()
            assert source._get_client() is first
            assert len(made) == 1

            first.is_closed = True
            assert source._get_client() is not first
            assert len(made) == 2

    @pytest.mark.asyncio
    async def test_search_matches_title_desc_and_tags(self) -> None:
        agents = [
            {"identifier": "a", "meta": {"title": "Alpha", "description": "d", "tags": ["pdf"]}},
            {"identifier": "b", "meta": {"title": "Beta", "description": "handles pdf", "tags": []}},
        ]
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.lobehub.create_httpx_client",
            return_value=_stub_client(payload=agents),
        ):
            source = LobeHubSource()
            assert [r.id for r in await source.search("alpha")] == ["lobehub/a"]
            assert [r.id for r in await source.search("pdf")] == ["lobehub/a", "lobehub/b"]

    @pytest.mark.asyncio
    async def test_blank_query_browses(self) -> None:
        agents = [{"identifier": "a"}, {"identifier": "b"}]
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.lobehub.create_httpx_client",
            return_value=_stub_client(payload=agents),
        ):
            source = LobeHubSource()
            assert len(await source.search("  ")) == 2
            assert len(await source.search("", limit=1)) == 1

    @pytest.mark.asyncio
    async def test_search_skips_non_dict_meta(self) -> None:
        agents = [{"identifier": "a", "meta": "not a dict"}, {"identifier": "b", "meta": {"title": "b"}}]
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.lobehub.create_httpx_client",
            return_value=_stub_client(payload=agents),
        ):
            source = LobeHubSource()
            assert [r.id for r in await source.search("b")] == ["lobehub/b"]

    @pytest.mark.asyncio
    async def test_search_returns_empty_on_index_error(self) -> None:
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.lobehub.create_httpx_client",
            return_value=_stub_client(status=500),
        ):
            assert await LobeHubSource().search("a") == []

    @pytest.mark.asyncio
    async def test_search_returns_empty_on_transport_error(self) -> None:
        client = _stub_client()
        client.get = AsyncMock(side_effect=RuntimeError("boom"))
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.lobehub.create_httpx_client",
            return_value=client,
        ):
            assert await LobeHubSource().search("a") == []

    @pytest.mark.asyncio
    async def test_index_accepts_agents_and_items_keys(self) -> None:
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.lobehub.create_httpx_client",
            return_value=_stub_client(payload={"agents": [{"identifier": "a"}]}),
        ):
            assert len(await LobeHubSource().search("")) == 1

        with patch(
            "myrm_agent_harness.agent.skills.market.sources.lobehub.create_httpx_client",
            return_value=_stub_client(payload={"items": [{"identifier": "b"}]}),
        ):
            assert len(await LobeHubSource().search("")) == 1

    @pytest.mark.asyncio
    async def test_index_rejects_malformed_payload(self) -> None:
        for payload in ({"agents": "nope"}, "scalar"):
            with patch(
                "myrm_agent_harness.agent.skills.market.sources.lobehub.create_httpx_client",
                return_value=_stub_client(payload=payload),
            ):
                assert await LobeHubSource().search("") == []

    @pytest.mark.asyncio
    async def test_index_is_cached(self) -> None:
        client = _stub_client(payload=[{"identifier": "a"}])
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.lobehub.create_httpx_client",
            return_value=client,
        ):
            source = LobeHubSource()
            await source.search("")
            await source.search("")

        assert client.get.await_count == 1

    @pytest.mark.asyncio
    async def test_failed_reload_keeps_previous_cache(self) -> None:
        source = LobeHubSource()
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.lobehub.create_httpx_client",
            return_value=_stub_client(payload=[{"identifier": "a"}]),
        ):
            await source.search("")
        source._cache_ts = 0.0

        with patch(
            "myrm_agent_harness.agent.skills.market.sources.lobehub.create_httpx_client",
            return_value=_stub_client(status=500),
        ):
            assert len(await source.search("")) == 1

    @pytest.mark.asyncio
    async def test_get_detail_strips_prefix(self) -> None:
        client = _stub_client(payload={"meta": {"title": "Agent", "description": "d"}, "author": "acme"})
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.lobehub.create_httpx_client",
            return_value=client,
        ):
            result = await LobeHubSource().get_detail("lobehub/agent")
        assert result.id == "lobehub/agent"
        assert result.author == "acme"
        assert "agent" in client.get.await_args.args[0]

    @pytest.mark.asyncio
    async def test_get_detail_without_prefix(self) -> None:
        client = _stub_client(payload={"title": "Agent"})
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.lobehub.create_httpx_client",
            return_value=client,
        ):
            assert (await LobeHubSource().get_detail("agent")).id == "lobehub/agent"

    @pytest.mark.asyncio
    async def test_get_detail_non_200_returns_none(self) -> None:
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.lobehub.create_httpx_client",
            return_value=_stub_client(status=404),
        ):
            assert await LobeHubSource().get_detail("agent") is None

    @pytest.mark.asyncio
    async def test_get_detail_rejects_non_dict(self) -> None:
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.lobehub.create_httpx_client",
            return_value=_stub_client(payload=["nope"]),
        ):
            assert await LobeHubSource().get_detail("agent") is None

    @pytest.mark.asyncio
    async def test_get_detail_error_returns_none(self) -> None:
        client = _stub_client()
        client.get = AsyncMock(side_effect=httpx.TimeoutException("slow"))
        with patch(
            "myrm_agent_harness.agent.skills.market.sources.lobehub.create_httpx_client",
            return_value=client,
        ):
            assert await LobeHubSource().get_detail("agent") is None

    def test_unknown_agent_shape_is_placeholder(self) -> None:
        result = LobeHubSource()._agent_to_result("junk")
        assert result.id == "unknown"
        assert result.name == "unknown"

    def test_agent_falls_back_to_top_level_meta(self) -> None:
        result = LobeHubSource()._agent_to_result({"title": "T", "author": "acme"})
        assert result.id == "lobehub/T"
        assert result.author == "acme"
        assert result.install_method == "direct"

    def test_agent_ignores_non_list_tags(self) -> None:
        result = LobeHubSource()._agent_to_result({"identifier": "a", "tags": "nope"})
        assert result.tags == []

    def test_detail_falls_back_when_meta_invalid(self) -> None:
        result = LobeHubSource()._agent_detail_to_result("agent", {"meta": "nope", "title": "T"})
        assert result.name == "T"

    def test_detail_ignores_non_list_tags(self) -> None:
        result = LobeHubSource()._agent_detail_to_result("agent", {"tags": "nope"})
        assert result.tags == []

    def test_detail_defaults_title_to_id(self) -> None:
        result = LobeHubSource()._agent_detail_to_result("agent", {})
        assert result.name == "agent"

    def test_description_is_truncated(self) -> None:
        result = LobeHubSource()._agent_to_result({"identifier": "a", "description": "x" * 500})
        assert len(result.description) == 200
