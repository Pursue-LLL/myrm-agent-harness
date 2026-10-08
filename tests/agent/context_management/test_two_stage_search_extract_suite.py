"""Comprehensive unit test suite for two-stage ranked snippet and selective deep extract suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.two_stage_search_extract import (
    DeepExtractResult,
    FetchBudgetExceededError,
    FetchBudgetGovernor,
    RankedSnippetTriageEngine,
    SearchFetchSessionCache,
    SelectiveDeepExtractCleaner,
    SnippetTriageResult,
    TwoStageRankedSnippetAndSelectiveDeepExtractSuite,
    TwoStageSearchConfig,
)


def test_ranked_snippet_triage_engine_and_token_budget_cap() -> None:
    """Validate Stage 1 snippet condensation, domain parsing, and strict 500-token budget cap."""
    config = TwoStageSearchConfig(
        max_snippet_tokens_budget=200,
        snippet_char_limit=100,
    )
    engine = RankedSnippetTriageEngine(config=config)

    raw_candidates = [
        {
            "title": f"Candidate Result {i}",
            "url": f"https://example.com/docs/page_{i}?utm_source=test",
            "score": 0.95 - (i * 0.05),
            "content": (
                f"Detailed technical documentation paragraph for item {i}. "
                "This contains exhaustive explanations about distributed consensus, "
                "replicated state machines, network partitions, and failover semantics."
            ),
        }
        for i in range(1, 15)
    ]

    triage_result = engine.triage_candidates(
        query="distributed state machines failover",
        raw_candidates=raw_candidates,
    )

    # 1. Total tokens must stay strictly bounded within the configured budget cap
    assert triage_result.total_estimated_tokens <= 200
    assert len(triage_result.items) > 0
    assert len(triage_result.items) < 15  # Budget cap must prune trailing items

    # 2. Check snippet formatting and domain extraction
    first_item = triage_result.items[0]
    assert first_item.index == 1
    assert first_item.domain == "example.com"
    assert len(first_item.snippet) <= 105
    assert "..." in first_item.snippet or len(first_item.snippet) <= 100

    # 3. Meta-guidance directive must be injected
    assert "METAGUIDANCE" in triage_result.guidance_directive
    assert "web_fetch" in triage_result.guidance_directive


def test_selective_deep_extract_cleaner_noise_removal() -> None:
    """Validate Stage 2 boilerplate stripping, markdown normalization, and compression ratio."""
    cleaner = SelectiveDeepExtractCleaner()

    raw_html = """
    <html>
      <head>
        <title>FastAPI Architecture</title>
        <script>console.log("analytics tracking");</script>
        <style>.sidebar { display: none; }</style>
      </head>
      <body>
        <nav>
          <a href="/home">Home</a>
          <a href="/pricing">Pricing</a>
        </nav>
        <header>
          <h1>Marketing Banner</h1>
        </header>
        <main>
          <h2>Core Concurrency Model</h2>
          <p>FastAPI uses AnyIO and Starlette under the hood for event loop multiplexing.</p>
          <p>Dependencies are evaluated using dependency injection graphs.</p>
        </main>
        <footer>
          <p>All rights reserved. Cookie policy and terms of service.</p>
        </footer>
      </body>
    </html>
    """

    result = cleaner.clean_raw_html_or_text(
        url="https://fastapi.tiangolo.com/advanced/architecture",
        title="FastAPI Architecture",
        raw_content=raw_html,
        fetch_turn=1,
    )

    assert result.url == "https://fastapi.tiangolo.com/advanced/architecture"
    assert result.title == "FastAPI Architecture"
    assert "# FastAPI Architecture" in result.cleaned_markdown
    assert "Core Concurrency Model" in result.cleaned_markdown
    assert "FastAPI uses AnyIO and Starlette" in result.cleaned_markdown

    # Ensure noisy script, nav, header, and footer boilerplate are stripped
    assert "<script>" not in result.cleaned_markdown
    assert "analytics tracking" not in result.cleaned_markdown
    assert "<style>" not in result.cleaned_markdown
    assert "Pricing" not in result.cleaned_markdown
    assert "Cookie policy" not in result.cleaned_markdown

    # Assert compression achieved
    assert result.cleaned_char_len < result.original_char_len
    assert result.compression_ratio < 1.0


def test_session_coalescing_cache_normalization_and_ttl() -> None:
    """Validate session cache query normalization, tracking param stripping, and stats."""
    cache = SearchFetchSessionCache(ttl_seconds=300)

    # 1. Test Query Triage caching with normalization
    sample_triage = SnippetTriageResult(
        query="Vector Search Indexing",
        items=[],
        total_estimated_tokens=50,
        cached=False,
    )
    cache.put_triage("  Vector Search, Indexing!  ", sample_triage)

    # Retrieve with differently spaced/punctuated equivalent query
    hit = cache.get_triage("vector search indexing")
    assert hit is not None
    assert hit.cached is True

    # Test bypass cache
    bypass_hit = cache.get_triage("vector search indexing", bypass_cache=True)
    assert bypass_hit is None

    # 2. Test Deep Extract URL caching with tracking parameter stripping
    sample_extract = DeepExtractResult(
        url="https://docs.kernel.org/subsystem",
        title="Kernel Docs",
        cleaned_markdown="# Kernel Docs Content",
        original_char_len=200,
        cleaned_char_len=80,
        compression_ratio=0.4,
    )
    cache.put_extract(
        "https://docs.kernel.org/subsystem/?utm_source=twitter&utm_medium=social",
        sample_extract,
    )

    # Lookup without marketing params
    url_hit = cache.get_extract("https://docs.kernel.org/subsystem")
    assert url_hit is not None
    assert url_hit.cached is True
    assert url_hit.title == "Kernel Docs"

    # Check stats
    stats = cache.get_stats()
    assert stats.triage_hits == 1
    assert stats.triage_misses == 1  # From bypass_hit
    assert stats.extract_hits == 1


def test_fetch_budget_governor_concurrency_and_interim_synthesis() -> None:
    """Validate concurrency capping (max 2 URLs), session ceiling, and interim synthesis gates."""
    config = TwoStageSearchConfig(
        max_concurrent_fetches_per_turn=2,
        max_accumulated_fetches_per_session=5,
        interim_synthesis_threshold=3,
    )
    governor = FetchBudgetGovernor(config=config)
    session_id = "test_session_turn_limits"

    # 1. Reject requests exceeding per-turn concurrency
    with pytest.raises(FetchBudgetExceededError, match="exceeds max concurrent per-turn limit"):
        governor.check_and_authorize_fetches(session_id, requested_count=3)

    # 2. Perform Turn 1 (2 fetches)
    governor.check_and_authorize_fetches(session_id, requested_count=2)
    s1 = governor.commit_turn_fetches(session_id, performed_count=2)
    assert s1.accumulated_fetches == 2
    assert s1.requires_interim_synthesis is False

    # 3. Perform Turn 2 (1 fetch)
    governor.check_and_authorize_fetches(session_id, requested_count=1)
    s2 = governor.commit_turn_fetches(session_id, performed_count=1)
    assert s2.accumulated_fetches == 3
    assert s2.requires_interim_synthesis is False

    # 4. Perform Turn 3 (1 fetch) -> should trigger interim synthesis requirement
    governor.check_and_authorize_fetches(session_id, requested_count=1)
    s3 = governor.commit_turn_fetches(session_id, performed_count=1)
    assert s3.accumulated_fetches == 4
    assert s3.requires_interim_synthesis is True

    # Model acknowledges interim synthesis
    governor.reset_consecutive_turns(session_id)
    s_reset = governor.get_status(session_id)
    assert s_reset.requires_interim_synthesis is False

    # 5. Exhaust total budget (already at 4, adding 2 would exceed session ceiling of 5)
    with pytest.raises(FetchBudgetExceededError, match="would exceed session ceiling"):
        governor.check_and_authorize_fetches(session_id, requested_count=2)


def test_two_stage_search_suite_end_to_end() -> None:
    """Validate end-to-end facade orchestrating triage, deep extract, caching, and budget."""
    config = TwoStageSearchConfig(
        max_snippet_tokens_budget=400,
        snippet_char_limit=90,
        max_concurrent_fetches_per_turn=2,
        max_accumulated_fetches_per_session=4,
    )
    suite = TwoStageRankedSnippetAndSelectiveDeepExtractSuite(config=config)
    session_id = "sess_e2e_research"

    candidates = [
        {
            "title": "PostgreSQL Optimization Guide",
            "url": "https://postgres.org/docs/opt",
            "score": 0.98,
            "content": "Comprehensive tuning guide for shared_buffers and effective_cache_size.",
        },
        {
            "title": "MySQL Buffer Pool Tuning",
            "url": "https://mysql.com/docs/tuning",
            "score": 0.85,
            "content": "InnoDB buffer pool tuning and memory allocation principles.",
        },
    ]

    # Stage 1: Triage
    triage = suite.triage_search_candidates("database buffer tuning", candidates)
    assert len(triage.items) == 2
    assert triage.cached is False

    # Repeated query hits session cache
    triage_cached = suite.triage_search_candidates("database buffer tuning", candidates)
    assert triage_cached.cached is True

    # Stage 2: Selective Deep Extract
    raw_pg_html = """
    <html><body>
      <nav>Sidebar Navigation</nav>
      <h1>PostgreSQL Optimization Guide</h1>
      <p>Set shared_buffers to 25% of system RAM for optimal caching.</p>
      <footer>Privacy notice</footer>
    </body></html>
    """

    extract = suite.selective_deep_extract(
        url="https://postgres.org/docs/opt",
        title="PostgreSQL Optimization Guide",
        raw_content=raw_pg_html,
        session_id=session_id,
    )
    assert extract.cached is False
    assert "shared_buffers to 25%" in extract.cleaned_markdown
    assert "Sidebar Navigation" not in extract.cleaned_markdown

    # Cache hit on duplicate fetch URL
    extract_cached = suite.selective_deep_extract(
        url="https://postgres.org/docs/opt",
        title="PostgreSQL Optimization Guide",
        raw_content=raw_pg_html,
        session_id=session_id,
    )
    assert extract_cached.cached is True

    # Verify governor budget status
    budget = suite.get_budget_status(session_id)
    assert budget.accumulated_fetches == 1
    assert budget.budget_exceeded is False

    # Batch extract testing
    batch_targets = [
        (
            "https://mysql.com/docs/tuning",
            "MySQL Tuning",
            "<html><body><p>innodb_buffer_pool_size parameter</p></body></html>",
        ),
    ]
    batch_results = suite.batch_deep_extract(batch_targets, session_id=session_id)
    assert len(batch_results) == 1
    assert "innodb_buffer_pool_size" in batch_results[0].cleaned_markdown

    final_budget = suite.get_budget_status(session_id)
    assert final_budget.accumulated_fetches == 2
