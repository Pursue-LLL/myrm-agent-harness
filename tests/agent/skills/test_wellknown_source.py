"""Unit tests for WellKnownSkillSource."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from myrm_agent_harness.agent.skills.market.sources.wellknown import (
    WellKnownSkillSource,
)


class TestWellKnownSkillSourceInit:
    def test_valid_url(self) -> None:
        source = WellKnownSkillSource("https://skills.company.com")
        assert source._base_url == "https://skills.company.com"
        assert (
            source._index_url
            == "https://skills.company.com/.well-known/skills/index.json"
        )

    def test_strips_trailing_slash(self) -> None:
        source = WellKnownSkillSource("https://skills.company.com/")
        assert source._base_url == "https://skills.company.com"

    def test_strips_path(self) -> None:
        source = WellKnownSkillSource("https://skills.company.com/some/path")
        assert source._base_url == "https://skills.company.com"

    def test_invalid_url_no_scheme(self) -> None:
        with pytest.raises(ValueError, match="must include scheme and host"):
            WellKnownSkillSource("skills.company.com")

    def test_invalid_url_empty(self) -> None:
        with pytest.raises(ValueError, match="must include scheme and host"):
            WellKnownSkillSource("")

    def test_source_name(self) -> None:
        source = WellKnownSkillSource("https://skills.example.com")
        assert source.source_name == "well-known:https://skills.example.com"


class TestWellKnownSkillSourceSearch:
    @pytest.fixture
    def source(self) -> WellKnownSkillSource:
        return WellKnownSkillSource("https://skills.test.com")

    @pytest.fixture
    def mock_index(self) -> list[dict[str, object]]:
        return [
            {
                "name": "code-review",
                "description": "Automated code review",
                "tags": ["dev", "quality"],
                "author": "team",
            },
            {
                "name": "data-analysis",
                "description": "Data analysis tools",
                "tags": ["data", "python"],
                "author": "team",
            },
            {
                "name": "deploy-helper",
                "description": "Deployment automation",
                "tags": ["devops"],
                "author": "ops",
            },
        ]

    @pytest.mark.asyncio
    async def test_search_empty_query_returns_all(
        self, source: WellKnownSkillSource, mock_index: list[dict[str, object]]
    ) -> None:
        with patch.object(
            source, "_fetch_index", new_callable=AsyncMock, return_value=mock_index
        ):
            results = await source.search("", limit=10)
            assert len(results) == 3

    @pytest.mark.asyncio
    async def test_search_keyword_match(
        self, source: WellKnownSkillSource, mock_index: list[dict[str, object]]
    ) -> None:
        with patch.object(
            source, "_fetch_index", new_callable=AsyncMock, return_value=mock_index
        ):
            results = await source.search("code review")
            assert len(results) == 1
            assert results[0].name == "code-review"

    @pytest.mark.asyncio
    async def test_search_tag_match(
        self, source: WellKnownSkillSource, mock_index: list[dict[str, object]]
    ) -> None:
        with patch.object(
            source, "_fetch_index", new_callable=AsyncMock, return_value=mock_index
        ):
            results = await source.search("devops")
            assert len(results) == 1
            assert results[0].name == "deploy-helper"

    @pytest.mark.asyncio
    async def test_search_respects_limit(
        self, source: WellKnownSkillSource, mock_index: list[dict[str, object]]
    ) -> None:
        with patch.object(
            source, "_fetch_index", new_callable=AsyncMock, return_value=mock_index
        ):
            results = await source.search("", limit=2)
            assert len(results) == 2

    @pytest.mark.asyncio
    async def test_search_returns_empty_on_fetch_failure(
        self, source: WellKnownSkillSource
    ) -> None:
        with patch.object(
            source, "_fetch_index", new_callable=AsyncMock, return_value=None
        ):
            results = await source.search("anything")
            assert results == []

    @pytest.mark.asyncio
    async def test_search_result_fields(
        self, source: WellKnownSkillSource, mock_index: list[dict[str, object]]
    ) -> None:
        with patch.object(
            source, "_fetch_index", new_callable=AsyncMock, return_value=mock_index
        ):
            results = await source.search("code")
            r = results[0]
            assert r.id == "well-known:https://skills.test.com/code-review"
            assert r.source == "well-known:https://skills.test.com"
            assert r.author == "team"
            assert (
                r.install_url
                == "https://skills.test.com/.well-known/skills/code-review/SKILL.md"
            )


class TestWellKnownSkillSourceGetDetail:
    @pytest.fixture
    def source(self) -> WellKnownSkillSource:
        return WellKnownSkillSource("https://skills.test.com")

    @pytest.mark.asyncio
    async def test_get_detail_found(self, source: WellKnownSkillSource) -> None:
        index = [{"name": "my-skill", "description": "Desc", "tags": []}]
        with patch.object(
            source, "_fetch_index", new_callable=AsyncMock, return_value=index
        ):
            result = await source.get_detail(
                "well-known:https://skills.test.com/my-skill"
            )
            assert result is not None
            assert result.name == "my-skill"

    @pytest.mark.asyncio
    async def test_get_detail_not_found(self, source: WellKnownSkillSource) -> None:
        index = [{"name": "other-skill", "description": "Desc", "tags": []}]
        with patch.object(
            source, "_fetch_index", new_callable=AsyncMock, return_value=index
        ):
            result = await source.get_detail(
                "well-known:https://skills.test.com/missing"
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_get_detail_wrong_prefix(self, source: WellKnownSkillSource) -> None:
        result = await source.get_detail("github:some-skill")
        assert result is None


class TestWellKnownSkillSourceProbe:
    @pytest.fixture
    def source(self) -> WellKnownSkillSource:
        return WellKnownSkillSource("https://skills.test.com")

    @pytest.mark.asyncio
    async def test_probe_success(self, source: WellKnownSkillSource) -> None:
        index = [{"name": "s1"}, {"name": "s2"}, {"name": "s3"}]
        with patch.object(
            source, "_fetch_index", new_callable=AsyncMock, return_value=index
        ):
            reachable, count = await source.probe()
            assert reachable is True
            assert count == 3

    @pytest.mark.asyncio
    async def test_probe_unreachable(self, source: WellKnownSkillSource) -> None:
        with patch.object(
            source, "_fetch_index", new_callable=AsyncMock, return_value=None
        ):
            reachable, count = await source.probe()
            assert reachable is False
            assert count == 0


class TestWellKnownSkillSourceFetchIndex:
    @pytest.fixture
    def source(self) -> WellKnownSkillSource:
        return WellKnownSkillSource("https://skills.test.com")

    @pytest.mark.asyncio
    async def test_fetch_index_success(self, source: WellKnownSkillSource) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"skills": [{"name": "a"}]}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "myrm_agent_harness.agent.skills.market.sources.wellknown.create_httpx_client",
            return_value=mock_client,
        ):
            result = await source._fetch_index()
            assert result == [{"name": "a"}]

    @pytest.mark.asyncio
    async def test_fetch_index_non_200(self, source: WellKnownSkillSource) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "myrm_agent_harness.agent.skills.market.sources.wellknown.create_httpx_client",
            return_value=mock_client,
        ):
            result = await source._fetch_index()
            assert result is None

    @pytest.mark.asyncio
    async def test_fetch_index_timeout(self, source: WellKnownSkillSource) -> None:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "myrm_agent_harness.agent.skills.market.sources.wellknown.create_httpx_client",
            return_value=mock_client,
        ):
            result = await source._fetch_index()
            assert result is None

    @pytest.mark.asyncio
    async def test_fetch_index_invalid_json_structure(
        self, source: WellKnownSkillSource
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"skills": "not-a-list"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "myrm_agent_harness.agent.skills.market.sources.wellknown.create_httpx_client",
            return_value=mock_client,
        ):
            result = await source._fetch_index()
            assert result is None


class TestRegisterUnregisterSource:
    def test_register_source(self) -> None:
        svc = BaseSkillMarketService()
        initial_count = len(svc._sources)
        source = WellKnownSkillSource("https://private.corp.com")
        svc.register_source(source)
        assert len(svc._sources) == initial_count + 1
        assert svc._sources[-1].source_name == "well-known:https://private.corp.com"

    def test_register_source_idempotent(self) -> None:
        svc = BaseSkillMarketService()
        source = WellKnownSkillSource("https://private.corp.com")
        svc.register_source(source)
        count_after_first = len(svc._sources)
        svc.register_source(source)
        assert len(svc._sources) == count_after_first

    def test_unregister_source(self) -> None:
        svc = BaseSkillMarketService()
        source = WellKnownSkillSource("https://private.corp.com")
        svc.register_source(source)
        removed = svc.unregister_source("well-known:https://private.corp.com")
        assert removed is True
        assert not any(
            s.source_name == "well-known:https://private.corp.com" for s in svc._sources
        )

    def test_unregister_nonexistent(self) -> None:
        svc = BaseSkillMarketService()
        removed = svc.unregister_source("well-known:https://nonexistent.com")
        assert removed is False


# Need import for register/unregister tests
from myrm_agent_harness.agent.skills.market.service import BaseSkillMarketService
