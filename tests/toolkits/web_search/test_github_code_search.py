"""Unit tests for GitHub code search fast-path.

Tests cover:
- build_github_code_query query normalization and language extraction
- search_github_code execution with mock responses (success, rate limit, timeout, empty)
- Engine Code fast-path routing and graceful fallback to generic search

[POS]
Unit tests for github_code_search.py and its integration with WebSearchEngine.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from myrm_agent_harness.toolkits.web_search.core.common import SearchResult
from myrm_agent_harness.toolkits.web_search.processing.intent_optimizer import (
    SearchIntent,
    detect_search_intent,
)
from myrm_agent_harness.toolkits.web_search.providers.github_code_search import (
    build_github_code_query,
    search_github_code,
)


class TestBuildGithubCodeQuery:
    """Test query normalization and language qualifier extraction."""

    def test_empty_query(self) -> None:
        assert build_github_code_query("") == ""
        assert build_github_code_query("   ") == ""

    def test_extract_language_qualifier(self) -> None:
        result = build_github_code_query("rust raft tick_heartbeat implementation")
        assert "language:rust" in result
        assert "raft" in result
        assert "tick_heartbeat" in result
        # noise words stripped
        assert "implementation" not in result

    def test_extract_python_qualifier(self) -> None:
        result = build_github_code_query("python fastapi websocket auth example")
        assert "language:python" in result
        assert "fastapi" in result
        assert "websocket" in result
        assert "auth" in result
        assert "example" not in result

    def test_chinese_noise_filtering(self) -> None:
        result = build_github_code_query("寻找 webrtc aec 源码 实现")
        assert "webrtc" in result
        assert "aec" in result
        assert "源码" not in result
        assert "实现" not in result


class TestSearchGithubCode:
    """Test GitHub code search API execution and error handling."""

    @pytest.mark.asyncio
    async def test_success_with_text_matches(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "total_count": 1,
            "items": [
                {
                    "name": "raw_node.rs",
                    "path": "src/raw_node.rs",
                    "html_url": "https://github.com/tikv/raft-rs/blob/master/src/raw_node.rs",
                    "repository": {
                        "full_name": "tikv/raft-rs",
                    },
                    "text_matches": [
                        {
                            "fragment": "pub fn tick(&mut self) -> bool {\n    self.raft.tick()\n}",
                        }
                    ],
                }
            ],
        }

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = mock_response

        results = await search_github_code(
            "rust raft raw_node tick",
            max_results=3,
            api_token="test-token",
            client=mock_client,
        )

        assert results is not None
        assert len(results) == 1
        item = results[0]
        assert item.title == "tikv/raft-rs: src/raw_node.rs"
        assert item.link == "https://github.com/tikv/raft-rs/blob/master/src/raw_node.rs"
        assert "tikv/raft-rs" in item.snippet
        assert "pub fn tick" in item.snippet
        assert item.engines == ["github_code"]

        # Check request headers had Authorization
        mock_client.get.assert_called_once()
        call_headers = mock_client.get.call_args[1]["headers"]
        assert call_headers["Authorization"] == "Bearer test-token"

    @pytest.mark.asyncio
    async def test_rate_limit_or_auth_failure_returns_none(self) -> None:
        for status in (401, 403, 429):
            mock_response = MagicMock(spec=httpx.Response)
            mock_response.status_code = status
            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.get.return_value = mock_response

            result = await search_github_code("any query", client=mock_client)
            assert result is None, f"Status {status} should return None"

    @pytest.mark.asyncio
    async def test_network_timeout_returns_none(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = httpx.TimeoutException("Connection timed out")

        result = await search_github_code("any query", client=mock_client)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_items_returns_none(self) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"total_count": 0, "items": []}
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = mock_response

        result = await search_github_code("obscure_symbol_not_found", client=mock_client)
        assert result is None


class TestEngineCodeFastPath:
    """Test engine level routing and fallback."""

    def test_intent_detection_identifies_code(self) -> None:
        result = detect_search_intent("raft tick_heartbeat implementation rust github")
        assert result.intent == SearchIntent.CODE

    @pytest.mark.asyncio
    async def test_engine_code_fast_path_success(self) -> None:
        from myrm_agent_harness.toolkits.web_search.engine import WebSearchTools
        from myrm_agent_harness.toolkits.web_search.providers.web_searcher import (
            SearchServiceConfig,
            WebSearcher,
        )

        mock_searcher = MagicMock(spec=WebSearcher)
        mock_searcher.config = SearchServiceConfig(search_service="searxng")

        engine = WebSearchTools(searcher=mock_searcher)

        sample_result = SearchResult(
            title="tikv/raft-rs: src/raw_node.rs",
            link="https://github.com/tikv/raft-rs/blob/master/src/raw_node.rs",
            snippet="Repository: tikv/raft-rs\nCode Fragment:\npub fn tick()",
            engines=["github_code"],
        )

        with patch(
            "myrm_agent_harness.toolkits.web_search.providers.github_code_search.search_github_code",
            new_callable=AsyncMock,
        ) as mock_search_code:
            mock_search_code.return_value = [sample_result]

            response = await engine.fast_search_with_questions(
                questions=["tikv raft rust implementation"],
                search_results_per_query=2,
            )

            assert response is not None
            assert len(response.documents) >= 1
            doc = response.documents[0]
            assert "tikv/raft-rs" in doc.page_content

    @pytest.mark.asyncio
    async def test_engine_code_fast_path_fallback_on_failure(self) -> None:
        from myrm_agent_harness.toolkits.web_search.engine import WebSearchTools
        from myrm_agent_harness.toolkits.web_search.providers.web_searcher import (
            SearchServiceConfig,
            WebSearcher,
        )

        mock_searcher = MagicMock(spec=WebSearcher)
        mock_searcher.config = SearchServiceConfig(search_service="searxng")

        fallback_search_result = [
            SearchResult(
                title="GitHub - TiKV Raft",
                link="https://github.com/tikv/raft-rs",
                snippet="TiKV Raft implementation in Rust",
                engines=["searxng"],
            )
        ]
        mock_searcher.multi_query_parallel_search = AsyncMock(return_value=[fallback_search_result])

        engine = WebSearchTools(searcher=mock_searcher)

        with patch(
            "myrm_agent_harness.toolkits.web_search.providers.github_code_search.search_github_code",
            new_callable=AsyncMock,
        ) as mock_search_code:
            # Simulate rate limit or network failure
            mock_search_code.return_value = None

            response = await engine.fast_search_with_questions(
                questions=["tikv raft rust implementation"],
                search_results_per_query=2,
            )

            assert response is not None
            assert len(response.documents) >= 1
            # Verify multi_query_parallel_search was invoked with fallback query containing site:github.com
            mock_searcher.multi_query_parallel_search.assert_called_once()
            fallback_query = mock_searcher.multi_query_parallel_search.call_args[0][0][0]
            assert "site:github.com" in fallback_query
