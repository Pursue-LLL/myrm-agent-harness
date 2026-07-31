"""Unit tests for Volcengine Doubao native search adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from myrm_agent_harness.toolkits.web_search.exceptions import SearchAPIError
from myrm_agent_harness.toolkits.web_search.volcengine_doubao_search import (
    VolcengineDoubaoSearch,
)


def _sample_response() -> dict[str, object]:
    return {
        "Result": {
            "ResultCount": 1,
            "WebResults": [
                {
                    "Title": "Example News",
                    "Url": "https://example.com/news",
                    "Snippet": "short",
                    "Summary": "Longer summary from NeedSummary.",
                    "SiteName": "Example",
                    "AuthInfoDes": "Very authoritative",
                    "PublishTime": "2026-07-29",
                }
            ],
        }
    }


@pytest.mark.asyncio
async def test_volcengine_search_parses_web_results() -> None:
    client = VolcengineDoubaoSearch(api_key="test-key", timeout_seconds=10)
    mock_response = httpx.Response(200, json=_sample_response())
    mock_response.request = httpx.Request("POST", "https://example.com")

    mock_http = MagicMock()
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "myrm_agent_harness.toolkits.web_search.volcengine_doubao_search.create_httpx_client",
        return_value=mock_http,
    ):
        results = await client.search("test query", num_results=3)

    assert len(results) == 1
    assert results[0].title == "Example News"
    assert results[0].link == "https://example.com/news"
    assert results[0].summary == "Longer summary from NeedSummary."
    assert results[0].date == "2026-07-29"
    assert results[0].site_name == "Example"
    assert results[0].authority_description == "Very authoritative"


@pytest.mark.asyncio
async def test_volcengine_search_raises_on_api_error_code() -> None:
    client = VolcengineDoubaoSearch(api_key="test-key", timeout_seconds=10)
    mock_response = httpx.Response(
        200,
        json={
            "ResponseMetadata": {
                "Error": {"Code": "10406", "Message": "quota exhausted"},
            }
        },
    )
    mock_response.request = httpx.Request("POST", "https://example.com")

    mock_http = MagicMock()
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "myrm_agent_harness.toolkits.web_search.volcengine_doubao_search.create_httpx_client",
        return_value=mock_http,
    ):
        with pytest.raises(SearchAPIError, match="10406"):
            await client.search("quota test", num_results=1)


@pytest.mark.asyncio
async def test_volcengine_search_raises_on_http_429() -> None:
    client = VolcengineDoubaoSearch(api_key="test-key", timeout_seconds=10)
    mock_response = httpx.Response(429, text="rate limited")
    mock_response.request = httpx.Request("POST", "https://example.com")

    mock_http = MagicMock()
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "myrm_agent_harness.toolkits.web_search.volcengine_doubao_search.create_httpx_client",
        return_value=mock_http,
    ):
        with pytest.raises(SearchAPIError, match="429"):
            await client.search("rate limit test", num_results=1)


def test_volcengine_requires_non_empty_api_key() -> None:
    with pytest.raises(ValueError, match="requires api_key"):
        VolcengineDoubaoSearch(api_key="   ")


def test_volcengine_build_body_optional_fields() -> None:
    client = VolcengineDoubaoSearch(api_key="test-key")
    body = client._build_body(
        query="q",
        count=5,
        extra={
            "TimeRange": "OneWeek",
            "AuthInfoLevel": 2,
            "QueryRewrite": True,
            "NeedSummary": False,
        },
    )
    assert body["TimeRange"] == "OneWeek"
    assert body["Filter"] == {"AuthInfoLevel": 2}
    assert body["QueryControl"] == {"QueryRewrite": True}
    assert body["NeedSummary"] is False


@pytest.mark.asyncio
async def test_volcengine_search_timeout_raises() -> None:
    client = VolcengineDoubaoSearch(api_key="test-key", timeout_seconds=1)
    mock_http = MagicMock()
    mock_http.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "myrm_agent_harness.toolkits.web_search.volcengine_doubao_search.create_httpx_client",
        return_value=mock_http,
    ):
        with pytest.raises(SearchAPIError, match="timed out"):
            await client.search("timeout test", num_results=1)


@pytest.mark.asyncio
async def test_volcengine_search_http_error_raises() -> None:
    client = VolcengineDoubaoSearch(api_key="test-key")
    mock_http = MagicMock()
    mock_http.post = AsyncMock(side_effect=httpx.ConnectError("connection failed"))
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "myrm_agent_harness.toolkits.web_search.volcengine_doubao_search.create_httpx_client",
        return_value=mock_http,
    ):
        with pytest.raises(SearchAPIError, match="HTTP error"):
            await client.search("connect test", num_results=1)


@pytest.mark.asyncio
async def test_volcengine_search_http_500_raises() -> None:
    client = VolcengineDoubaoSearch(api_key="test-key")
    mock_response = httpx.Response(500, text="internal error")
    mock_response.request = httpx.Request("POST", "https://example.com")
    mock_http = MagicMock()
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "myrm_agent_harness.toolkits.web_search.volcengine_doubao_search.create_httpx_client",
        return_value=mock_http,
    ):
        with pytest.raises(SearchAPIError, match="HTTP 500"):
            await client.search("server error", num_results=1)


@pytest.mark.asyncio
async def test_volcengine_search_invalid_json_raises() -> None:
    client = VolcengineDoubaoSearch(api_key="test-key")
    mock_response = httpx.Response(200, text="not-json")
    mock_response.request = httpx.Request("POST", "https://example.com")
    mock_http = MagicMock()
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "myrm_agent_harness.toolkits.web_search.volcengine_doubao_search.create_httpx_client",
        return_value=mock_http,
    ):
        with pytest.raises(SearchAPIError, match="invalid JSON"):
            await client.search("bad json", num_results=1)


@pytest.mark.asyncio
async def test_volcengine_search_empty_or_malformed_results() -> None:
    client = VolcengineDoubaoSearch(api_key="test-key")
    mock_response = httpx.Response(
        200,
        json={
            "Result": "not-a-dict",
        },
    )
    mock_response.request = httpx.Request("POST", "https://example.com")
    mock_http = MagicMock()
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "myrm_agent_harness.toolkits.web_search.volcengine_doubao_search.create_httpx_client",
        return_value=mock_http,
    ):
        assert await client.search("empty block", num_results=1) == []

    mock_response2 = httpx.Response(
        200,
        json={"Result": {"WebResults": ["bad-item", {"Title": "Ok", "Url": "https://x.com"}]}},
    )
    mock_response2.request = httpx.Request("POST", "https://example.com")
    mock_http.post = AsyncMock(return_value=mock_response2)
    with patch(
        "myrm_agent_harness.toolkits.web_search.volcengine_doubao_search.create_httpx_client",
        return_value=mock_http,
    ):
        results = await client.search("partial", num_results=1)
    assert len(results) == 1
    assert results[0].title == "Ok"


@pytest.mark.asyncio
async def test_volcengine_search_summary_backfills_snippet() -> None:
    client = VolcengineDoubaoSearch(api_key="test-key")
    mock_response = httpx.Response(
        200,
        json={
            "Result": {
                "WebResults": [
                    {
                        "Title": "Only Summary",
                        "Url": "https://example.com/s",
                        "Summary": "A" * 600,
                    }
                ]
            }
        },
    )
    mock_response.request = httpx.Request("POST", "https://example.com")
    mock_http = MagicMock()
    mock_http.post = AsyncMock(return_value=mock_response)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "myrm_agent_harness.toolkits.web_search.volcengine_doubao_search.create_httpx_client",
        return_value=mock_http,
    ):
        results = await client.search("summary only", num_results=1)

    assert len(results) == 1
    assert results[0].snippet == "A" * 500
    assert results[0].summary == "A" * 600
