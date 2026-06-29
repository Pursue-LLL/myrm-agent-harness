"""ModelScopeSource 单元测试

使用 monkeypatch 模拟 httpx 响应，不发真实网络请求。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.skills.discovery.sources.modelscope import (
    ModelScopeSource,
    _int,
    _str,
)


def _make_mock_response(status_code: int, json_data: object) -> MagicMock:
    """Create a mock httpx.Response (sync json() method)."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


@pytest.fixture
def source() -> ModelScopeSource:
    return ModelScopeSource()


class TestSourceName:
    def test_source_name(self, source: ModelScopeSource) -> None:
        assert source.source_name == "modelscope"


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_success(self, source: ModelScopeSource) -> None:
        resp = _make_mock_response(200, {
            "success": True,
            "data": {
                "skills": [
                    {
                        "id": "@test/mcp-weather",
                        "display_name": "Weather MCP",
                        "description": "Get weather info",
                        "developer": "test-dev",
                        "downloads": 1500,
                        "view_count": 3000,
                        "version": "1.0.0",
                        "category": "Utilities",
                    }
                ]
            },
        })

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=resp)

        with patch("myrm_agent_harness.agent.skills.discovery.sources.modelscope.httpx.AsyncClient", return_value=mock_client):
            results = await source.search("weather", limit=10)

        assert len(results) == 1
        r = results[0]
        assert r.id == "@test/mcp-weather"
        assert r.name == "Weather MCP"
        assert r.description == "Get weather info"
        assert r.source == "modelscope"
        assert r.author == "test-dev"
        assert r.downloads == 1500
        assert r.stars == 3000
        assert r.install_method == "direct"
        assert r.version == "1.0.0"
        assert "Utilities" in r.tags
        assert "modelscope.cn/skills" in r.install_url

    @pytest.mark.asyncio
    async def test_search_empty_query(self, source: ModelScopeSource) -> None:
        resp = _make_mock_response(200, {"success": True, "data": {"skills": []}})

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=resp)

        with patch("myrm_agent_harness.agent.skills.discovery.sources.modelscope.httpx.AsyncClient", return_value=mock_client):
            results = await source.search("", limit=10)

        assert results == []

    @pytest.mark.asyncio
    async def test_search_http_error(self, source: ModelScopeSource) -> None:
        resp = _make_mock_response(500, None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=resp)

        with patch("myrm_agent_harness.agent.skills.discovery.sources.modelscope.httpx.AsyncClient", return_value=mock_client):
            results = await source.search("test", limit=5)

        assert results == []

    @pytest.mark.asyncio
    async def test_search_timeout(self, source: ModelScopeSource) -> None:
        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with patch("myrm_agent_harness.agent.skills.discovery.sources.modelscope.httpx.AsyncClient", return_value=mock_client):
            results = await source.search("test", limit=5)

        assert results == []

    @pytest.mark.asyncio
    async def test_search_invalid_json(self, source: ModelScopeSource) -> None:
        resp = _make_mock_response(200, {"success": False})

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=resp)

        with patch("myrm_agent_harness.agent.skills.discovery.sources.modelscope.httpx.AsyncClient", return_value=mock_client):
            results = await source.search("test", limit=5)

        assert results == []

    @pytest.mark.asyncio
    async def test_search_limit_clamped(self, source: ModelScopeSource) -> None:
        """Limit should be clamped to MAX_PAGE_SIZE."""
        resp = _make_mock_response(200, {"success": True, "data": {"skills": []}})

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=resp)

        with patch("myrm_agent_harness.agent.skills.discovery.sources.modelscope.httpx.AsyncClient", return_value=mock_client):
            await source.search("test", limit=200)

        call_kwargs = mock_client.get.call_args
        params = call_kwargs.kwargs.get("params", call_kwargs[1].get("params", {}))
        assert params["page_size"] == 100

    @pytest.mark.asyncio
    async def test_search_localized_description(self, source: ModelScopeSource) -> None:
        resp = _make_mock_response(200, {
            "success": True,
            "data": {
                "skills": [
                    {
                        "id": "test-skill",
                        "display_name": "Test",
                        "locales": {
                            "zh": {"description": "中文描述"},
                            "en": {"description": "English desc"},
                        },
                        "developer": "dev",
                    }
                ]
            },
        })

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=resp)

        with patch("myrm_agent_harness.agent.skills.discovery.sources.modelscope.httpx.AsyncClient", return_value=mock_client):
            results = await source.search("test", limit=5)

        assert len(results) == 1
        assert results[0].description == "中文描述"


class TestGetDetail:
    @pytest.mark.asyncio
    async def test_get_detail_success(self, source: ModelScopeSource) -> None:
        resp = _make_mock_response(200, {
            "success": True,
            "data": {
                "id": "@org/skill-x",
                "display_name": "Skill X",
                "description": "A skill",
                "developer": "org",
                "version": "2.0",
            },
        })

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=resp)

        with patch("myrm_agent_harness.agent.skills.discovery.sources.modelscope.httpx.AsyncClient", return_value=mock_client):
            result = await source.get_detail("@org/skill-x")

        assert result is not None
        assert result.id == "@org/skill-x"
        assert result.name == "Skill X"
        assert result.version == "2.0"

    @pytest.mark.asyncio
    async def test_get_detail_not_found(self, source: ModelScopeSource) -> None:
        resp = _make_mock_response(404, None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=resp)

        with patch("myrm_agent_harness.agent.skills.discovery.sources.modelscope.httpx.AsyncClient", return_value=mock_client):
            result = await source.get_detail("nonexistent")

        assert result is None


class TestHelpers:
    def test_str_with_string(self) -> None:
        assert _str("hello ") == "hello"

    def test_str_with_none(self) -> None:
        assert _str(None) == ""

    def test_str_with_int(self) -> None:
        assert _str(42) == ""

    def test_int_with_int(self) -> None:
        assert _int(42) == 42

    def test_int_with_bool(self) -> None:
        assert _int(True) == 0

    def test_int_with_none(self) -> None:
        assert _int(None) == 0

    def test_int_with_string(self) -> None:
        assert _int("123") == 0


class TestParseItem:
    @pytest.mark.asyncio
    async def test_author_from_id_prefix(self, source: ModelScopeSource) -> None:
        """When developer/owner is missing, extract from @org/name id."""
        resp = _make_mock_response(200, {
            "success": True,
            "data": {
                "skills": [
                    {
                        "id": "@myorg/tool",
                        "display_name": "Tool",
                        "description": "desc",
                    }
                ]
            },
        })

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=resp)

        with patch("myrm_agent_harness.agent.skills.discovery.sources.modelscope.httpx.AsyncClient", return_value=mock_client):
            results = await source.search("tool", limit=5)

        assert results[0].author == "myorg"

    def test_item_without_id_skipped(self, source: ModelScopeSource) -> None:
        result = source._parse_item({"display_name": "No ID"})
        assert result is None
