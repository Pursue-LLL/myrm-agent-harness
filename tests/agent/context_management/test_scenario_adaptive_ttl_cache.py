"""Comprehensive test suite for scenario-adaptive dynamic TTL scheduling and cache transparency."""

from __future__ import annotations

import time

from myrm_agent_harness.agent.context_management.two_stage_search_extract import (
    AdaptiveTtlConfig,
    DeepExtractResult,
    RankedSnippetItem,
    SearchFetchSessionCache,
    SnippetTriageResult,
    TimeSensitivityScenario,
    TimeSensitivityTtlAdvisor,
    TwoStageRankedSnippetAndSelectiveDeepExtractSuite,
    TwoStageSearchConfig,
)


def test_time_sensitivity_ttl_advisor_scenarios() -> None:
    """Validate query and URL classification into realtime, standard, and archive scenarios."""
    config = AdaptiveTtlConfig(
        realtime_ttl_seconds=120,
        standard_ttl_seconds=1200,
        archive_ttl_seconds=72000,
    )
    advisor = TimeSensitivityTtlAdvisor(config)

    # 1. Realtime query detection
    scenario, ttl = advisor.evaluate_query("比特币今日实时价格与大盘行情")
    assert scenario == TimeSensitivityScenario.REALTIME
    assert ttl == 120

    scenario, ttl = advisor.evaluate_query("breaking news live crypto alerts")
    assert scenario == TimeSensitivityScenario.REALTIME
    assert ttl == 120

    # 2. Archive query detection
    scenario, ttl = advisor.evaluate_query("RFC 9110 HTTP Semantics specification")
    assert scenario == TimeSensitivityScenario.ARCHIVE
    assert ttl == 72000

    scenario, ttl = advisor.evaluate_query("Python 解释器历史与架构起源")
    assert scenario == TimeSensitivityScenario.ARCHIVE
    assert ttl == 72000

    # 3. Standard fallback query detection
    scenario, ttl = advisor.evaluate_query("FastAPI dependency injection best practices")
    assert scenario == TimeSensitivityScenario.STANDARD
    assert ttl == 1200

    # 4. URL classification
    scenario, ttl = advisor.evaluate_url("https://en.wikipedia.org/wiki/Raft_consensus")
    assert scenario == TimeSensitivityScenario.ARCHIVE
    assert ttl == 72000

    scenario, ttl = advisor.evaluate_url("https://www.ietf.org/rfc/rfc6749.txt")
    assert scenario == TimeSensitivityScenario.ARCHIVE
    assert ttl == 72000

    scenario, ttl = advisor.evaluate_url("https://example.com/tickers/quotes/live")
    assert scenario == TimeSensitivityScenario.REALTIME
    assert ttl == 120

    # 5. Explicit scenario override
    scenario, ttl = advisor.evaluate_query(
        "today stock quote",
        explicit_scenario=TimeSensitivityScenario.ARCHIVE,
    )
    assert scenario == TimeSensitivityScenario.ARCHIVE
    assert ttl == 72000


def test_session_coalescing_cache_adaptive_ttl_and_token_savings() -> None:
    """Validate per-entry TTL expiry, token savings tracking, and scenario hit counters."""
    cache = SearchFetchSessionCache(ttl_seconds=1800)

    snippet_item = RankedSnippetItem(
        index=1,
        title="Crypto Live Rate",
        url="https://crypto.example/rate",
        domain="crypto.example",
        snippet="BTC current rate is 65000 USD",
        estimated_tokens=50,
    )
    sample_triage = SnippetTriageResult(
        query="crypto live rate",
        items=[snippet_item],
        total_estimated_tokens=80,
    )

    # Put realtime triage with 1-second TTL for immediate expiry validation
    cache.put_triage(
        query="crypto live rate",
        result=sample_triage,
        ttl_seconds=1,
        scenario="realtime",
        estimated_tokens=500,
    )

    # Immediate lookup: hits cache
    hit = cache.get_triage("crypto live rate")
    assert hit is not None
    assert hit.cached is True
    assert hit.cache_age_seconds >= 0
    assert hit.saved_tokens == 500
    assert hit.scenario == "realtime"

    # Sleep past TTL and verify expiry eviction
    time.sleep(1.05)
    expired_hit = cache.get_triage("crypto live rate")
    assert expired_hit is None

    # Deep extract caching with long archive TTL
    sample_extract = DeepExtractResult(
        url="https://docs.python.org/3/tutorial",
        title="Python Tutorial",
        cleaned_markdown="# Python Tutorial Overview",
        original_char_len=4000,
        cleaned_char_len=1200,
        compression_ratio=0.3,
    )
    cache.put_extract(
        url="https://docs.python.org/3/tutorial",
        result=sample_extract,
        ttl_seconds=86400,
        scenario="archive",
        estimated_tokens=1000,
    )

    extract_hit = cache.get_extract("https://docs.python.org/3/tutorial")
    assert extract_hit is not None
    assert extract_hit.cached is True
    assert extract_hit.scenario == "archive"
    assert extract_hit.saved_tokens == 1000

    # Force bypass cache
    bypass_extract = cache.get_extract("https://docs.python.org/3/tutorial", bypass_cache=True)
    assert bypass_extract is None

    # Verify telemetry stats
    stats = cache.get_stats()
    assert stats.triage_hits == 1
    assert stats.triage_misses >= 1  # Expired lookup was a miss
    assert stats.extract_hits == 1
    assert stats.extract_misses == 1  # From bypass lookup
    assert stats.total_saved_tokens == 1500  # 500 (triage) + 1000 (extract)
    assert stats.realtime_hits == 1
    assert stats.archive_hits == 1
    assert stats.standard_hits == 0


def test_suite_end_to_end_adaptive_caching_and_transparency() -> None:
    """Validate end-to-end facade orchestrating adaptive TTL assignment and transparency metadata."""
    config = TwoStageSearchConfig(
        max_snippet_tokens_budget=400,
        adaptive_ttl=AdaptiveTtlConfig(
            realtime_ttl_seconds=60,
            standard_ttl_seconds=600,
            archive_ttl_seconds=3600,
        ),
    )
    suite = TwoStageRankedSnippetAndSelectiveDeepExtractSuite(config=config)
    session_id = "test_e2e_adaptive_session"

    raw_candidates = [
        {
            "title": "Bitcoin Price Breaking Update",
            "url": "https://news.example/btc-live",
            "score": 0.99,
            "content": "Bitcoin spikes following ETF flow announcement.",
        }
    ]

    # Turn 1: Triage realtime search
    res1 = suite.triage_search_candidates("bitcoin breaking live price", raw_candidates)
    assert res1.cached is False

    # Turn 2: Cache hit on duplicate query
    res2 = suite.triage_search_candidates("bitcoin breaking live price", raw_candidates)
    assert res2.cached is True
    assert res2.scenario == "realtime"
    assert res2.saved_tokens > 0

    # Turn 3: Bypass cache (Force Refresh)
    res3 = suite.triage_search_candidates(
        "bitcoin breaking live price",
        raw_candidates,
        bypass_cache=True,
    )
    assert res3.cached is False

    # Deep extract with archive URL
    archive_url = "https://en.wikipedia.org/wiki/Consensus_algorithm"
    raw_html = "<html><body><h1>Consensus</h1><p>Formal consensus theory</p></body></html>"

    ext1 = suite.selective_deep_extract(
        url=archive_url,
        title="Consensus Algorithm",
        raw_content=raw_html,
        session_id=session_id,
    )
    assert ext1.cached is False

    ext2 = suite.selective_deep_extract(
        url=archive_url,
        title="Consensus Algorithm",
        raw_content=raw_html,
        session_id=session_id,
    )
    assert ext2.cached is True
    assert ext2.scenario == "archive"
    assert ext2.saved_tokens >= 500

    # Stats validation
    stats = suite.get_cache_stats()
    assert stats.realtime_hits == 1
    assert stats.archive_hits == 1
    assert stats.total_saved_tokens > 0
