"""Unit tests for the ClawHub and well-known skill sources.

[INPUT]
- myrm_agent_harness.agent.skills.market.sources.clawhub
- myrm_agent_harness.agent.skills.market.sources.wellknown

[OUTPUT]
- pytest suite covering search and detail parsing, best-effort enrichment,
  client reuse, and well-known index discovery. All HTTP is stubbed.

[POS]
myrm-agent-harness/tests/agent/skills/market/sources/test_clawhub_wellknown.py
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from myrm_agent_harness.agent.skills.market.sources.clawhub import (
    ClawHubSource,
    _extract_owner,
    _safe_int,
    _url_encode_slug,
)
from myrm_agent_harness.agent.skills.market.sources.wellknown import WellKnownSkillSource

BASE = "https://clawhub.test"


def _patch_base(monkeypatch: pytest.MonkeyPatch, base: str = BASE) -> None:
    monkeypatch.setattr(
        "myrm_agent_harness.agent.skills.market.sources.clawhub.resolve_registry_base_url",
        lambda: base,
    )


def _client(status: int = 200, payload: object = None, text: str = "") -> MagicMock:
    client = MagicMock()
    client.is_closed = False
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload if payload is not None else {}
    response.text = text
    client.get = AsyncMock(return_value=response)
    return client


class TestClawHubHelpers:
    def test_url_encodes_slash(self) -> None:
        assert _url_encode_slug("owner/skill") == "owner%2Fskill"

    def test_extract_owner(self) -> None:
        assert _extract_owner("owner/skill") == "owner"
        assert _extract_owner("skill") == ""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(5, 5), ("7", 7), (None, 0), ("abc", 0), (1.9, 1)],
    )
    def test_safe_int(self, value: object, expected: int) -> None:
        assert _safe_int(value) == expected

    def test_token_from_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAWHUB_TOKEN", "tok")
        assert ClawHubSource()._build_headers()["Authorization"] == "Bearer tok"

    def test_blank_token_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAWHUB_TOKEN", "   ")
        assert "Authorization" not in ClawHubSource()._build_headers()

    def test_source_name(self) -> None:
        assert ClawHubSource().source_name == "clawhub"


def _stub_client_factory(monkeypatch: pytest.MonkeyPatch) -> list[MagicMock]:
    """Replace the real client factory so lifecycle state is fully controllable."""
    created: list[MagicMock] = []

    def _factory(**_kwargs: object) -> MagicMock:
        client = _client()
        created.append(client)
        return client

    monkeypatch.setattr("myrm_agent_harness.agent.skills.market.sources.clawhub.create_httpx_client", _factory)
    return created


class TestClawHubClientLifecycle:
    def test_client_is_reused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        created = _stub_client_factory(monkeypatch)
        source = ClawHubSource()

        first = source._get_client()

        assert source._get_client() is first
        assert len(created) == 1

    def test_closed_client_is_recreated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        created = _stub_client_factory(monkeypatch)
        source = ClawHubSource()

        first = source._get_client()
        first.is_closed = True

        assert source._get_client() is not first
        assert len(created) == 2

    def test_base_url_change_recreates_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch, "https://one.test")
        _stub_client_factory(monkeypatch)
        source = ClawHubSource()
        first = source._get_client()

        monkeypatch.setattr(
            "myrm_agent_harness.agent.skills.market.sources.clawhub.resolve_registry_base_url",
            lambda: "https://two.test",
        )

        assert source._get_client() is not first

    def test_reset_client_clears_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        _stub_client_factory(monkeypatch)
        source = ClawHubSource()
        source._get_client()

        source.reset_client()

        assert source._client is None
        assert source._client_base_url is None

    def test_reset_client_drops_open_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        _stub_client_factory(monkeypatch)
        source = ClawHubSource()
        source._get_client()
        assert source._client is not None

        source.reset_client()

        # 契约：丢弃仍打开的连接池；已关闭的引用保留
        assert source._client is None

    def test_reset_client_keeps_already_closed_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        _stub_client_factory(monkeypatch)
        source = ClawHubSource()
        client = source._get_client()
        client.is_closed = True

        source.reset_client()

        assert source._client is client

    def test_reset_client_without_client_is_safe(self) -> None:
        source = ClawHubSource()
        source.reset_client()
        assert source._client is None


class TestClawHubSearch:
    @pytest.mark.asyncio
    async def test_parses_wrapped_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        source = ClawHubSource()
        client = _client(
            payload={
                "results": [
                    {
                        "slug": "owner/alpha",
                        "displayName": "Alpha",
                        "summary": "does things",
                        "score": 12,
                        "keywords": ["a", 3],
                    }
                ]
            }
        )
        source._get_client = MagicMock(return_value=client)
        source._enrich_results = AsyncMock()

        results = await source.search("alpha")

        assert [r.id for r in results] == ["owner/alpha"]
        assert results[0].author == "owner"
        assert results[0].keywords == ["a"]
        assert results[0].install_method == "zip"

    @pytest.mark.asyncio
    async def test_parses_bare_list_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        source = ClawHubSource()
        source._get_client = MagicMock(return_value=_client(payload=[{"slug": "x"}]))
        source._enrich_results = AsyncMock()
        assert [r.id for r in await source.search("x")] == ["x"]

    @pytest.mark.asyncio
    async def test_skips_items_without_slug(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        source = ClawHubSource()
        source._get_client = MagicMock(return_value=_client(payload={"results": ["junk", {"slug": "ok"}]}))
        source._enrich_results = AsyncMock()
        assert [r.id for r in await source.search("x")] == ["ok"]

    @pytest.mark.asyncio
    async def test_non_200_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        source = ClawHubSource()
        source._get_client = MagicMock(return_value=_client(status=500))
        assert await source.search("x") == []

    @pytest.mark.asyncio
    async def test_timeout_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        source = ClawHubSource()
        client = MagicMock()
        client.get = AsyncMock(side_effect=httpx.TimeoutException("slow"))
        source._get_client = MagicMock(return_value=client)
        assert await source.search("x") == []

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        source = ClawHubSource()
        client = MagicMock()
        client.get = AsyncMock(side_effect=RuntimeError("boom"))
        source._get_client = MagicMock(return_value=client)
        assert await source.search("x") == []

    @pytest.mark.asyncio
    async def test_blank_query_sends_wildcard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        source = ClawHubSource()
        client = _client(payload=[])
        source._get_client = MagicMock(return_value=client)
        await source.search("   ")
        assert client.get.await_args.kwargs["params"]["q"] == "*"

    def test_parse_search_response_rejects_scalar(self) -> None:
        assert ClawHubSource()._parse_search_response("scalar") == []  # type: ignore[arg-type]

    def test_parse_search_response_rejects_bad_field(self) -> None:
        assert ClawHubSource()._parse_search_response({"results": "no"}) == []

    def test_item_falls_back_to_snake_case_fields(self) -> None:
        result = ClawHubSource()._search_item_to_result(
            {"slug": "s", "display_name": "Snake", "description": "d", "package_type": "agent_plugin"}
        )
        assert result.name == "Snake"
        assert result.description == "d"
        assert result.package_type == "agent_plugin"


class TestClawHubDetail:
    @pytest.mark.asyncio
    async def test_rejects_blank_id(self) -> None:
        assert await ClawHubSource().get_detail("   ") is None

    @pytest.mark.asyncio
    async def test_parses_full_detail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        source = ClawHubSource()
        source._get_client = MagicMock(
            return_value=_client(
                payload={
                    "skill": {
                        "displayName": "Alpha",
                        "summary": "s",
                        "stats": {"stars": 5, "downloads": 7},
                        "tags": ["x"],
                        "keywords": ["k"],
                    },
                    "latestVersion": {"version": "2.0.0"},
                    "owner": {"handle": "owner"},
                }
            )
        )
        result = await source.get_detail("owner/alpha")
        assert result.version == "2.0.0"
        assert result.stars == 5
        assert result.downloads == 7
        assert result.author == "owner"

    @pytest.mark.asyncio
    async def test_falls_back_to_slug_owner(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        source = ClawHubSource()
        source._get_client = MagicMock(
            return_value=_client(payload={"skill": {"stats": {"installsCurrent": 3}}, "owner": {}})
        )
        result = await source.get_detail("owner/alpha")
        assert result.author == "owner"
        assert result.downloads == 3

    @pytest.mark.asyncio
    async def test_missing_skill_field_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        source = ClawHubSource()
        source._get_client = MagicMock(return_value=_client(payload={"nope": 1}))
        assert await source.get_detail("owner/alpha") is None

    @pytest.mark.asyncio
    async def test_non_200_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        source = ClawHubSource()
        source._get_client = MagicMock(return_value=_client(status=404))
        assert await source.get_detail("owner/alpha") is None

    @pytest.mark.asyncio
    async def test_error_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        source = ClawHubSource()
        client = MagicMock()
        client.get = AsyncMock(side_effect=RuntimeError("boom"))
        source._get_client = MagicMock(return_value=client)
        assert await source.get_detail("owner/alpha") is None

    def test_dict_tags_are_flattened(self) -> None:
        result = ClawHubSource()._parse_detail_response("owner/alpha", {"skill": {"tags": {"k": "v"}}})
        assert result.tags == ["v"]

    def test_missing_stats_defaults_to_zero(self) -> None:
        result = ClawHubSource()._parse_detail_response("owner/alpha", {"skill": {}})
        assert result.stars == 0
        assert result.downloads == 0


class TestClawHubEnrichment:
    @pytest.mark.asyncio
    async def test_enriches_with_detail_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        source = ClawHubSource()
        results = [source._search_item_to_result({"slug": "owner/alpha"})]
        client = _client(payload={"skill": {"summary": "enriched", "stats": {"stars": 9}}})

        await source._enrich_results(client, results)

        assert results[0].description == "enriched"
        assert results[0].stars == 9

    @pytest.mark.asyncio
    async def test_enrichment_keeps_original_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        source = ClawHubSource()
        results = [source._search_item_to_result({"slug": "owner/alpha"})]
        client = _client(status=500)

        await source._enrich_results(client, results)

        assert results[0].description == ""

    @pytest.mark.asyncio
    async def test_enrichment_ignores_malformed_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_base(monkeypatch)
        source = ClawHubSource()
        results = [source._search_item_to_result({"slug": "owner/alpha"})]
        client = _client(payload={"nope": 1})

        await source._enrich_results(client, results)

        assert results[0].description == ""


class TestWellKnownSource:
    def test_rejects_url_without_scheme(self) -> None:
        with pytest.raises(ValueError, match="scheme and host"):
            WellKnownSkillSource("example.com")

    def test_strips_path_and_trailing_slash(self) -> None:
        source = WellKnownSkillSource("https://reg.test/ignored/")
        assert source._base_url == "https://reg.test"
        assert source.source_name == "well-known:https://reg.test"

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_matches_name_and_tags(self) -> None:
        respx.get("https://reg.test/.well-known/skills/index.json").mock(
            return_value=httpx.Response(
                200,
                json={
                    "skills": [
                        {"name": "alpha", "description": "first", "tags": ["pdf"]},
                        {"name": "beta", "description": "second"},
                    ]
                },
            )
        )
        source = WellKnownSkillSource("https://reg.test")

        assert [r.name for r in await source.search("alpha")] == ["alpha"]
        assert [r.name for r in await source.search("pdf")] == ["alpha"]
        assert [r.name for r in await source.search("")] == ["alpha", "beta"]
        assert await source.search("absent") == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_respects_limit(self) -> None:
        respx.get("https://reg.test/.well-known/skills/index.json").mock(
            return_value=httpx.Response(200, json={"skills": [{"name": "a"}, {"name": "b"}]})
        )
        assert len(await WellKnownSkillSource("https://reg.test").search("", limit=1)) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_all_terms_must_match(self) -> None:
        respx.get("https://reg.test/.well-known/skills/index.json").mock(
            return_value=httpx.Response(200, json={"skills": [{"name": "alpha", "description": "beta"}]})
        )
        source = WellKnownSkillSource("https://reg.test")
        # 两个词分别落在 name 与 description 上，均命中
        assert len(await source.search("alpha beta")) == 1
        assert await source.search("alpha gamma") == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_detail_finds_and_misses(self) -> None:
        respx.get("https://reg.test/.well-known/skills/index.json").mock(
            return_value=httpx.Response(200, json={"skills": [{"name": "alpha"}]})
        )
        source = WellKnownSkillSource("https://reg.test")

        assert (await source.get_detail("well-known:https://reg.test/alpha")).name == "alpha"
        assert await source.get_detail("well-known:https://reg.test/absent") is None
        assert await source.get_detail("other-format") is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_probe_reports_counts(self) -> None:
        respx.get("https://reg.test/.well-known/skills/index.json").mock(
            return_value=httpx.Response(200, json={"skills": [{"name": "a"}]})
        )
        assert await WellKnownSkillSource("https://reg.test").probe() == (True, 1)

    @pytest.mark.asyncio
    @respx.mock
    async def test_probe_reports_unreachable(self) -> None:
        respx.get("https://reg.test/.well-known/skills/index.json").mock(return_value=httpx.Response(404))
        assert await WellKnownSkillSource("https://reg.test").probe() == (False, 0)

    @pytest.mark.asyncio
    @respx.mock
    async def test_malformed_skills_field_is_unreachable(self) -> None:
        respx.get("https://reg.test/.well-known/skills/index.json").mock(
            return_value=httpx.Response(200, json={"skills": "nope"})
        )
        source = WellKnownSkillSource("https://reg.test")
        assert await source._fetch_index() is None
        assert await source.probe() == (False, 0)

    @pytest.mark.asyncio
    @respx.mock
    async def test_timeout_is_unreachable(self) -> None:
        respx.get("https://reg.test/.well-known/skills/index.json").mock(side_effect=httpx.TimeoutException("slow"))
        assert await WellKnownSkillSource("https://reg.test")._fetch_index() is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_transport_error_is_unreachable(self) -> None:
        respx.get("https://reg.test/.well-known/skills/index.json").mock(side_effect=httpx.ConnectError("down"))
        assert await WellKnownSkillSource("https://reg.test")._fetch_index() is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_on_unreachable_index(self) -> None:
        respx.get("https://reg.test/.well-known/skills/index.json").mock(return_value=httpx.Response(500))
        assert await WellKnownSkillSource("https://reg.test").search("a") == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_detail_on_unreachable_index(self) -> None:
        respx.get("https://reg.test/.well-known/skills/index.json").mock(return_value=httpx.Response(500))
        source = WellKnownSkillSource("https://reg.test")
        assert await source.get_detail("well-known:https://reg.test/alpha") is None

    def test_install_url_defaults_and_method(self) -> None:
        source = WellKnownSkillSource("https://reg.test")
        plain = source._to_search_result({"name": "alpha"})
        assert plain.install_url == "https://reg.test/.well-known/skills/alpha/SKILL.md"
        assert plain.install_method == "zip"
        assert plain.readme_url is None

        git = source._to_search_result({"name": "b", "install_url": "https://x.test/b.git"})
        assert git.install_method == "git"

    def test_maps_optional_fields(self) -> None:
        result = WellKnownSkillSource("https://reg.test")._to_search_result(
            {
                "name": "a",
                "description": "d",
                "author": "acme",
                "version": "1.2.3",
                "stars": 4,
                "downloads": 5,
                "tags": ["t"],
                "readme_url": "https://x.test/readme",
                "packageType": "agent_plugin",
                "keywords": ["k", 7],
            }
        )
        assert result.version == "1.2.3"
        assert result.package_type == "agent_plugin"
        assert result.keywords == ["k"]
        assert result.readme_url == "https://x.test/readme"

    def test_matches_joins_all_fields(self) -> None:
        assert WellKnownSkillSource._matches("a b", "A", "b", []) is True
        assert WellKnownSkillSource._matches("tag", "n", "d", ["Tag"]) is True
        assert WellKnownSkillSource._matches("zz", "n", "d", []) is False
