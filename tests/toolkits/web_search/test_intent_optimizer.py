"""Search intent optimizer unit tests.

Tests for intent_optimizer.py covering:
- SearchIntent enum values
- SearchIntentResult dataclass
- KeywordSearchIntentDetector intent detection
- Priority ordering between intents
- Confidence scoring
- resolve_search_params parameter mapping
- detect_search_intent convenience function
- Edge cases: empty query, mixed-language, multi-keyword
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.web_search.intent_optimizer import (
    _CONFIDENCE_THRESHOLD,
    _SEARXNG_INTENT_PARAMS,
    _TAVILY_INTENT_PARAMS,
    KeywordSearchIntentDetector,
    SearchIntent,
    SearchIntentResult,
    detect_search_intent,
    resolve_search_params,
)


class TestSearchIntentEnum:
    """SearchIntent enum completeness."""

    def test_all_intents_defined(self):
        expected = {
            "code",
            "news",
            "finance",
            "academic",
            "social",
            "security",
            "general",
        }
        actual = {intent.value for intent in SearchIntent}
        assert actual == expected

    def test_intent_values_are_lowercase(self):
        for intent in SearchIntent:
            assert intent.value == intent.value.lower()


class TestSearchIntentResult:
    """SearchIntentResult dataclass behavior."""

    def test_creation(self):
        result = SearchIntentResult(intent=SearchIntent.CODE, confidence=0.9)
        assert result.intent == SearchIntent.CODE
        assert result.confidence == 0.9

    def test_immutability(self):
        result = SearchIntentResult(intent=SearchIntent.NEWS, confidence=0.7)
        with pytest.raises(AttributeError):
            result.intent = SearchIntent.CODE  # type: ignore[misc]

    def test_equality(self):
        r1 = SearchIntentResult(intent=SearchIntent.CODE, confidence=0.7)
        r2 = SearchIntentResult(intent=SearchIntent.CODE, confidence=0.7)
        assert r1 == r2


class TestKeywordSearchIntentDetector:
    """KeywordSearchIntentDetector detection logic."""

    @pytest.fixture
    def detector(self) -> KeywordSearchIntentDetector:
        return KeywordSearchIntentDetector()

    # --- NEWS intent ---
    @pytest.mark.parametrize(
        "query",
        [
            "latest python release",
            "breaking news about AI",
            "OpenAI announced GPT-5",
            "最新AI动态",
            "今天发布了新特性",
            "this week in tech",
            "本月更新了什么",
        ],
    )
    def test_news_intent(self, detector: KeywordSearchIntentDetector, query: str):
        result = detector.detect(query)
        assert result.intent == SearchIntent.NEWS
        assert result.confidence >= _CONFIDENCE_THRESHOLD

    # --- FINANCE intent ---
    @pytest.mark.parametrize(
        "query",
        [
            "NVIDIA stock price analysis",
            "OpenAI valuation 2026",
            "bitcoin market cap",
            "Anthropic funding round",
            "A股行情分析",
            "美股纳斯达克走势",
            "估值融资信息",
        ],
    )
    def test_finance_intent(self, detector: KeywordSearchIntentDetector, query: str):
        result = detector.detect(query)
        assert result.intent == SearchIntent.FINANCE
        assert result.confidence >= _CONFIDENCE_THRESHOLD

    # --- SECURITY intent ---
    @pytest.mark.parametrize(
        "query",
        [
            "CVE-2024-1234 details",
            "103.171.86.220 reputation",
            "malware analysis report",
            "virustotal scan results",
            "这个漏洞怎么利用",
            "xss注入攻击手法",
        ],
    )
    def test_security_intent(self, detector: KeywordSearchIntentDetector, query: str):
        result = detector.detect(query)
        assert result.intent == SearchIntent.SECURITY
        assert result.confidence >= _CONFIDENCE_THRESHOLD

    # --- ACADEMIC intent ---
    @pytest.mark.parametrize(
        "query",
        [
            "arxiv transformer paper 2024",
            "NeurIPS 2025 accepted papers",
            "machine learning research survey",
            "这篇论文的引用格式",
            "ICML学术会议投稿要求",
        ],
    )
    def test_academic_intent(self, detector: KeywordSearchIntentDetector, query: str):
        result = detector.detect(query)
        assert result.intent == SearchIntent.ACADEMIC
        assert result.confidence >= _CONFIDENCE_THRESHOLD

    # --- CODE intent ---
    @pytest.mark.parametrize(
        "query",
        [
            "github rust async runtime",
            "stackoverflow python decorator",
            "pip install langchain",
            "npm package for websocket",
            "这个开源框架怎么用",
            "看看源码实现",
        ],
    )
    def test_code_intent(self, detector: KeywordSearchIntentDetector, query: str):
        result = detector.detect(query)
        assert result.intent == SearchIntent.CODE
        assert result.confidence >= _CONFIDENCE_THRESHOLD

    # --- SOCIAL intent ---
    @pytest.mark.parametrize(
        "query",
        [
            "reddit discussion about Claude",
            "twitter AI community",
            "V2EX论坛上的讨论",
            "社区里的评价反馈",
        ],
    )
    def test_social_intent(self, detector: KeywordSearchIntentDetector, query: str):
        result = detector.detect(query)
        assert result.intent == SearchIntent.SOCIAL
        assert result.confidence >= _CONFIDENCE_THRESHOLD

    # --- GENERAL intent (no match) ---
    @pytest.mark.parametrize(
        "query",
        [
            "how to make a sandwich",
            "best vacation destinations",
            "what is the meaning of life",
            "如何做蛋炒饭",
            "天气预报",
        ],
    )
    def test_general_intent(self, detector: KeywordSearchIntentDetector, query: str):
        result = detector.detect(query)
        assert result.intent == SearchIntent.GENERAL
        assert result.confidence == 1.0

    # --- Priority: NEWS > CODE (e.g. "Python latest release") ---
    def test_news_priority_over_code(self, detector: KeywordSearchIntentDetector):
        result = detector.detect("Python latest release news")
        assert result.intent == SearchIntent.NEWS

    def test_news_priority_over_finance(self, detector: KeywordSearchIntentDetector):
        result = detector.detect("latest news about stock market")
        assert result.intent == SearchIntent.NEWS

    def test_news_priority_over_social(self, detector: KeywordSearchIntentDetector):
        """'hacker news' contains 'news' keyword — NEWS takes priority over SOCIAL."""
        result = detector.detect("hacker news top posts")
        assert result.intent == SearchIntent.NEWS

    # --- Confidence scoring ---
    def test_single_keyword_confidence(self, detector: KeywordSearchIntentDetector):
        result = detector.detect("github")
        assert result.confidence == pytest.approx(0.7, abs=0.01)

    def test_multiple_keywords_increase_confidence(
        self, detector: KeywordSearchIntentDetector
    ):
        result = detector.detect("github stackoverflow implementation source code")
        assert result.confidence >= 0.7

    def test_max_confidence_capped_at_1(self, detector: KeywordSearchIntentDetector):
        result = detector.detect(
            "github stackoverflow npm pypi implementation source code crate package"
        )
        assert result.confidence <= 1.0

    # --- Edge cases ---
    def test_empty_query(self, detector: KeywordSearchIntentDetector):
        result = detector.detect("")
        assert result.intent == SearchIntent.GENERAL
        assert result.confidence == 1.0

    def test_case_insensitivity(self, detector: KeywordSearchIntentDetector):
        result = detector.detect("GITHUB Repository")
        assert result.intent == SearchIntent.CODE

    def test_ip_address_triggers_security(self, detector: KeywordSearchIntentDetector):
        result = detector.detect("check 192.168.1.1 for threats")
        assert result.intent == SearchIntent.SECURITY


class TestResolveSearchParams:
    """resolve_search_params mapping logic."""

    # --- SearxNG provider ---
    def test_searxng_code_params(self):
        intent_result = SearchIntentResult(intent=SearchIntent.CODE, confidence=0.9)
        params = resolve_search_params(intent_result, "searxng")
        assert params == _SEARXNG_INTENT_PARAMS[SearchIntent.CODE]
        assert "engines" in params
        assert "github" in params["engines"]

    def test_searxng_news_params(self):
        intent_result = SearchIntentResult(intent=SearchIntent.NEWS, confidence=0.8)
        params = resolve_search_params(intent_result, "searxng")
        assert params is not None
        assert params["categories"] == "news"
        assert params["time_range"] == "day"

    def test_searxng_academic_params(self):
        intent_result = SearchIntentResult(intent=SearchIntent.ACADEMIC, confidence=0.7)
        params = resolve_search_params(intent_result, "searxng")
        assert params is not None
        assert "arxiv" in params["engines"]

    def test_searxng_social_params(self):
        intent_result = SearchIntentResult(intent=SearchIntent.SOCIAL, confidence=0.7)
        params = resolve_search_params(intent_result, "searxng")
        assert params is not None
        assert "reddit" in params["engines"]

    def test_searxng_finance_params(self):
        intent_result = SearchIntentResult(intent=SearchIntent.FINANCE, confidence=0.7)
        params = resolve_search_params(intent_result, "searxng")
        assert params is not None
        assert params["time_range"] == "week"

    def test_searxng_security_params(self):
        intent_result = SearchIntentResult(intent=SearchIntent.SECURITY, confidence=0.7)
        params = resolve_search_params(intent_result, "searxng")
        assert params is not None
        assert params["categories"] == "general"

    # --- Tavily provider ---
    def test_tavily_news_params(self):
        intent_result = SearchIntentResult(intent=SearchIntent.NEWS, confidence=0.9)
        params = resolve_search_params(intent_result, "tavily")
        assert params == _TAVILY_INTENT_PARAMS[SearchIntent.NEWS]
        assert params["topic"] == "news"

    def test_tavily_finance_params(self):
        intent_result = SearchIntentResult(intent=SearchIntent.FINANCE, confidence=0.9)
        params = resolve_search_params(intent_result, "tavily")
        assert params is not None
        assert params["topic"] == "finance"

    def test_tavily_code_returns_none(self):
        intent_result = SearchIntentResult(intent=SearchIntent.CODE, confidence=0.9)
        params = resolve_search_params(intent_result, "tavily")
        assert params is None

    # --- GENERAL intent returns None ---
    def test_general_intent_returns_none(self):
        intent_result = SearchIntentResult(intent=SearchIntent.GENERAL, confidence=1.0)
        params = resolve_search_params(intent_result, "searxng")
        assert params is None

    # --- Low confidence returns None ---
    def test_low_confidence_returns_none(self):
        intent_result = SearchIntentResult(intent=SearchIntent.CODE, confidence=0.5)
        params = resolve_search_params(intent_result, "searxng")
        assert params is None

    def test_threshold_boundary(self):
        just_below = SearchIntentResult(
            intent=SearchIntent.CODE, confidence=_CONFIDENCE_THRESHOLD - 0.01
        )
        assert resolve_search_params(just_below, "searxng") is None

        at_threshold = SearchIntentResult(
            intent=SearchIntent.CODE, confidence=_CONFIDENCE_THRESHOLD
        )
        assert resolve_search_params(at_threshold, "searxng") is not None

    # --- Unknown provider returns None ---
    def test_unknown_provider_returns_none(self):
        intent_result = SearchIntentResult(intent=SearchIntent.CODE, confidence=0.9)
        params = resolve_search_params(intent_result, "unknown_provider")
        assert params is None

    def test_perplexity_provider_returns_none(self):
        intent_result = SearchIntentResult(intent=SearchIntent.NEWS, confidence=0.9)
        params = resolve_search_params(intent_result, "perplexity")
        assert params is None


class TestDetectSearchIntentConvenience:
    """detect_search_intent module-level convenience function."""

    def test_returns_intent_result(self):
        result = detect_search_intent("github python library")
        assert isinstance(result, SearchIntentResult)
        assert result.intent == SearchIntent.CODE

    def test_general_fallback(self):
        result = detect_search_intent("how to cook pasta")
        assert result.intent == SearchIntent.GENERAL

    def test_uses_default_detector(self):
        r1 = detect_search_intent("latest AI news")
        detector = KeywordSearchIntentDetector()
        r2 = detector.detect("latest AI news")
        assert r1 == r2


class TestIntentIntegrationWithWebSearcher:
    """Integration: verify override is correctly passed through multi_query_parallel_search."""

    @pytest.mark.asyncio
    async def test_per_query_overrides_passed_to_search_and_process(self):
        """Verify per_query_overrides are correctly distributed to individual searches."""
        from unittest.mock import AsyncMock

        from myrm_agent_harness.toolkits.web_search.common import SearchResult
        from myrm_agent_harness.toolkits.web_search.web_searcher import (
            SearchServiceConfig,
            WebSearcher,
        )

        config = SearchServiceConfig(
            search_service="searxng", api_base="http://localhost:8081"
        )
        searcher = WebSearcher(config)

        mock_service = AsyncMock()
        mock_service.search = AsyncMock(
            return_value=[
                SearchResult(link="https://github.com/test", title="Test", snippet="S")
            ]
        )
        searcher._search_service = mock_service

        overrides = [
            {"engines": "github,stackoverflow", "categories": "it"},
            None,
        ]

        results = await searcher.multi_query_parallel_search(
            queries=["rust async code", "general question"],
            results_per_query=5,
            per_query_overrides=overrides,
        )

        assert len(results) == 2
        assert mock_service.search.call_count == 2

        first_call_kwargs = mock_service.search.call_args_list[0][1]
        assert first_call_kwargs.get("engines") == "github,stackoverflow"
        assert first_call_kwargs.get("categories") == "it"

    @pytest.mark.asyncio
    async def test_override_takes_precedence_over_config_extra_params(self):
        """Verify override params override config.extra_params."""
        from unittest.mock import AsyncMock

        from myrm_agent_harness.toolkits.web_search.common import SearchResult
        from myrm_agent_harness.toolkits.web_search.web_searcher import (
            SearchServiceConfig,
            WebSearcher,
        )

        config = SearchServiceConfig(
            search_service="searxng",
            api_base="http://localhost:8081",
            extra_params={"categories": "general", "language": "zh"},
        )
        searcher = WebSearcher(config)

        mock_service = AsyncMock()
        mock_service.search = AsyncMock(
            return_value=[SearchResult(link="https://test.com", title="T", snippet="S")]
        )
        searcher._search_service = mock_service

        unique_q = f"override_precedence_{id(searcher)}"
        await searcher.search(
            unique_q,
            num_results=5,
            extra_params_override={"categories": "news", "time_range": "day"},
        )

        call_kwargs = mock_service.search.call_args[1]
        assert call_kwargs["categories"] == "news"
        assert call_kwargs["time_range"] == "day"
        assert call_kwargs["language"] == "zh"

    @pytest.mark.asyncio
    async def test_cache_key_includes_override(self):
        """Different overrides for same query must NOT hit cache."""
        from unittest.mock import AsyncMock

        from myrm_agent_harness.toolkits.web_search.common import SearchResult
        from myrm_agent_harness.toolkits.web_search.web_searcher import (
            SearchServiceConfig,
            WebSearcher,
        )

        config = SearchServiceConfig(
            search_service="searxng", api_base="http://localhost:8081"
        )
        searcher = WebSearcher(config)

        mock_service = AsyncMock()
        mock_service.search = AsyncMock(
            return_value=[SearchResult(link="https://r.com", title="R", snippet="S")]
        )
        searcher._search_service = mock_service

        unique_q = f"cache_override_test_{id(searcher)}"

        await searcher.search(unique_q, 5, extra_params_override={"categories": "news"})
        await searcher.search(unique_q, 5, extra_params_override={"categories": "it"})

        assert mock_service.search.call_count == 2
