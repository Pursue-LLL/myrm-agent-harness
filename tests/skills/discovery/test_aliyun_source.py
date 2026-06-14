"""AliyunSource 单元测试

使用 monkeypatch 模拟环境变量和 SDK 响应，不发真实网络请求。
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.skills.discovery.sources.aliyun import (
    AliyunSource,
    _extract_skill_items,
    _opt_int,
    _str,
    _to_search_result,
)


@pytest.fixture
def source() -> AliyunSource:
    return AliyunSource()


@pytest.fixture
def env_with_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "test-ak-id")
    monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "test-ak-secret")


@pytest.fixture
def env_without_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", raising=False)


class TestSourceName:
    def test_source_name(self, source: AliyunSource) -> None:
        assert source.source_name == "aliyun"


class TestCredentialsCheck:
    def test_credentials_available_true(self, source: AliyunSource, env_with_creds: None) -> None:
        assert source._credentials_available() is True

    def test_credentials_available_false(self, source: AliyunSource, env_without_creds: None) -> None:
        assert source._credentials_available() is False

    def test_credentials_available_partial(self, source: AliyunSource, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "test-ak")
        monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", raising=False)
        assert source._credentials_available() is False


class TestSearchWithoutCredentials:
    @pytest.mark.asyncio
    async def test_search_returns_empty_without_creds(self, source: AliyunSource, env_without_creds: None) -> None:
        results = await source.search("test", limit=10)
        assert results == []

    @pytest.mark.asyncio
    async def test_get_detail_returns_none_without_creds(self, source: AliyunSource, env_without_creds: None) -> None:
        result = await source.get_detail("test-skill")
        assert result is None


class TestSearchWithCredentials:
    @pytest.mark.asyncio
    async def test_search_success(self, source: AliyunSource, env_with_creds: None) -> None:
        mock_resp = {
            "body": {
                "data": [
                    {
                        "skillName": "weather-tool",
                        "displayName": "Weather Tool",
                        "description": "Get weather",
                        "provider": "aliyun-dev",
                        "installCount": 500,
                        "likeCount": 100,
                        "categoryName": "Tools",
                        "subCategoryName": "Weather",
                        "version": "1.0",
                    }
                ]
            }
        }

        with patch.object(source, "_call_api", new_callable=AsyncMock, return_value=mock_resp["body"]):
            results = await source.search("weather", limit=10)

        assert len(results) == 1
        r = results[0]
        assert r.id == "weather-tool"
        assert r.name == "Weather Tool"
        assert r.description == "Get weather"
        assert r.source == "aliyun"
        assert r.author == "aliyun-dev"
        assert r.downloads == 500
        assert r.stars == 100
        assert r.install_method == "direct"
        assert "Tools" in r.tags
        assert "Weather" in r.tags

    @pytest.mark.asyncio
    async def test_search_api_error(self, source: AliyunSource, env_with_creds: None) -> None:
        with patch.object(source, "_call_api", new_callable=AsyncMock, side_effect=RuntimeError("API error")):
            results = await source.search("test", limit=5)

        assert results == []

    @pytest.mark.asyncio
    async def test_search_empty_results(self, source: AliyunSource, env_with_creds: None) -> None:
        with patch.object(source, "_call_api", new_callable=AsyncMock, return_value={"data": []}):
            results = await source.search("nonexistent", limit=5)

        assert results == []


class TestGetDetail:
    @pytest.mark.asyncio
    async def test_get_detail_success(self, source: AliyunSource, env_with_creds: None) -> None:
        mock_resp = {
            "skillName": "my-skill",
            "displayName": "My Skill",
            "description": "A great skill",
            "provider": "dev",
            "version": "2.0",
        }

        with patch.object(source, "_call_api", new_callable=AsyncMock, return_value=mock_resp):
            result = await source.get_detail("my-skill")

        assert result is not None
        assert result.id == "my-skill"
        assert result.name == "My Skill"
        assert result.version == "2.0"

    @pytest.mark.asyncio
    async def test_get_detail_api_error(self, source: AliyunSource, env_with_creds: None) -> None:
        with patch.object(source, "_call_api", new_callable=AsyncMock, side_effect=Exception("fail")):
            result = await source.get_detail("test")

        assert result is None


class TestHelpers:
    def test_str_with_string(self) -> None:
        assert _str(" hello ") == "hello"

    def test_str_with_none(self) -> None:
        assert _str(None) == ""

    def test_str_with_int(self) -> None:
        assert _str(42) == ""

    def test_opt_int_with_int(self) -> None:
        assert _opt_int(42) == 42

    def test_opt_int_with_bool(self) -> None:
        assert _opt_int(True) is None

    def test_opt_int_with_none(self) -> None:
        assert _opt_int(None) is None

    def test_opt_int_with_digit_string(self) -> None:
        assert _opt_int("123") == 123

    def test_opt_int_with_non_digit_string(self) -> None:
        assert _opt_int("abc") is None


class TestExtractSkillItems:
    def test_valid_body(self) -> None:
        body = {"data": [{"skillName": "a"}, {"skillName": "b"}]}
        assert len(_extract_skill_items(body)) == 2

    def test_invalid_body_no_data(self) -> None:
        assert _extract_skill_items({"other": []}) == []

    def test_invalid_body_not_dict(self) -> None:
        assert _extract_skill_items("string") == []

    def test_filters_non_dicts(self) -> None:
        body = {"data": [{"skillName": "a"}, "invalid", None, 42]}
        assert len(_extract_skill_items(body)) == 1


class TestToSearchResult:
    def test_valid_item(self) -> None:
        item = {
            "skillName": "test-skill",
            "displayName": "Test Skill",
            "description": "Description",
            "provider": "author",
            "installCount": 10,
            "likeCount": 5,
            "categoryName": "Cat",
            "version": "1.0",
        }
        result = _to_search_result(item)
        assert result is not None
        assert result.id == "test-skill"
        assert result.name == "Test Skill"
        assert result.source == "aliyun"
        assert result.downloads == 10
        assert result.stars == 5

    def test_item_without_names_returns_none(self) -> None:
        assert _to_search_result({}) is None
        assert _to_search_result({"description": "no name"}) is None

    def test_deduplicates_category_subcategory(self) -> None:
        item = {
            "skillName": "s",
            "displayName": "S",
            "categoryName": "Same",
            "subCategoryName": "Same",
        }
        result = _to_search_result(item)
        assert result is not None
        assert result.tags == ["Same"]

    def test_fallback_to_skillname_when_no_display(self) -> None:
        item = {"skillName": "raw-name"}
        result = _to_search_result(item)
        assert result is not None
        assert result.name == "raw-name"
        assert result.id == "raw-name"
