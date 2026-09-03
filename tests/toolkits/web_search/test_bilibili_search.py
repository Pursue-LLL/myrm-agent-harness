"""Unit tests for Bilibili search fast-path.

Tests cover:
- Intent detection for PLATFORM_BILIBILI
- bilibili_search edge cases (mocked HTTP)
- Integration with engine routing logic

[POS]
Unit tests for bilibili_search.py and its integration with intent_optimizer/engine.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.web_search.processing.intent_optimizer import (
    SearchIntent,
    SearchIntentResult,
    detect_search_intent,
    resolve_search_params,
)
from myrm_agent_harness.toolkits.web_search.providers.bilibili_search import (
    _format_play_count,
    _strip_html,
    search_bilibili,
)


class TestIntentDetectionBilibili:
    """PLATFORM_BILIBILI intent detection precision."""

    @pytest.mark.parametrize(
        "query",
        [
            "搜B站上关于LLM的视频",
            "B站上有没有Rust教程",
            "找B站关于K8s的教程",
            "搜b站AI视频",
            "哔哩哔哩上搜Python教程",
            "site:bilibili.com LLM",
        ],
    )
    def test_positive_detection(self, query: str) -> None:
        result = detect_search_intent(query)
        assert result.intent == SearchIntent.PLATFORM_BILIBILI

    @pytest.mark.parametrize(
        "query",
        [
            "bilibili stock price",
            "Python latest news",
            "how to use docker",
            "bilibili company revenue 2026",
        ],
    )
    def test_negative_detection(self, query: str) -> None:
        result = detect_search_intent(query)
        assert result.intent != SearchIntent.PLATFORM_BILIBILI

    def test_resolve_params_returns_none(self) -> None:
        """PLATFORM_BILIBILI is handled by engine directly, not search params."""
        result = resolve_search_params(
            SearchIntentResult(intent=SearchIntent.PLATFORM_BILIBILI, confidence=0.9),
            "searxng",
        )
        assert result is None


class TestStripHtml:
    """HTML tag removal utility."""

    def test_removes_em_tags(self) -> None:
        assert _strip_html('<em class="keyword">Python</em>教程') == "Python教程"

    def test_removes_nested_tags(self) -> None:
        assert _strip_html("<b><em>hello</em></b>") == "hello"

    def test_no_tags(self) -> None:
        assert _strip_html("plain text") == "plain text"

    def test_empty_string(self) -> None:
        assert _strip_html("") == ""


class TestFormatPlayCount:
    """Play count formatting (万 unit)."""

    def test_below_threshold(self) -> None:
        assert _format_play_count(9999) == "9999"

    def test_exactly_10000(self) -> None:
        assert _format_play_count(10000) == "1.0万"

    def test_large_number(self) -> None:
        assert _format_play_count(1681000) == "168.1万"

    def test_zero(self) -> None:
        assert _format_play_count(0) == "0"


class TestSearchBilibili:
    """search_bilibili function with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_empty_keyword_returns_none(self) -> None:
        assert await search_bilibili("") is None
        assert await search_bilibili("  ") is None

    @pytest.mark.asyncio
    async def test_max_results_clamped(self) -> None:
        mock_response = {
            "code": 0,
            "data": {
                "result": [
                    {
                        "result_type": "video",
                        "data": [
                            {
                                "title": f"Video {i}",
                                "author": "UP",
                                "play": 1000,
                                "duration": "10:00",
                                "bvid": f"BV{i:010d}",
                                "description": "desc",
                            }
                            for i in range(5)
                        ],
                    }
                ]
            },
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(mock_response).encode("utf-8")
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = await search_bilibili("test", max_results=0)
            assert result is not None
            assert len(result) == 1  # clamped to min 1

    @pytest.mark.asyncio
    async def test_api_returns_null_data(self) -> None:
        """Regression: API returns {"code": 0, "data": null}."""
        mock_response = {"code": 0, "data": None}
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(mock_response).encode("utf-8")
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = await search_bilibili("test", max_results=5)
            assert result is None  # graceful fallback

    @pytest.mark.asyncio
    async def test_api_returns_nonzero_code(self) -> None:
        mock_response = {"code": -412, "data": None}
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(mock_response).encode("utf-8")
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = await search_bilibili("test", max_results=5)
            assert result is None

    @pytest.mark.asyncio
    async def test_successful_search(self) -> None:
        mock_response = {
            "code": 0,
            "data": {
                "result": [
                    {
                        "result_type": "video",
                        "data": [
                            {
                                "title": '<em class="keyword">Rust</em>教程',
                                "author": "软件工艺师",
                                "play": 1681000,
                                "duration": "729:37",
                                "bvid": "BV1hp4y1k7SV",
                                "description": "配套教材",
                            }
                        ],
                    }
                ]
            },
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(mock_response).encode("utf-8")
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            results = await search_bilibili("Rust教程", max_results=5)
            assert results is not None
            assert len(results) == 1
            r = results[0]
            assert r.title == "Rust教程"  # HTML cleaned
            assert r.link == "https://www.bilibili.com/video/BV1hp4y1k7SV"
            assert "168.1万" in r.snippet
            assert "软件工艺师" in r.snippet

    @pytest.mark.asyncio
    async def test_network_error_returns_none(self) -> None:
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            result = await search_bilibili("test", max_results=3)
            assert result is None
