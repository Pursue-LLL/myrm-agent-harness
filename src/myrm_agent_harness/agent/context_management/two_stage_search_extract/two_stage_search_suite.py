# [INPUT] RankedSnippetTriageEngine, SelectiveDeepExtractCleaner, SearchFetchSessionCache, FetchBudgetGovernor
# [OUTPUT] TwoStageRankedSnippetAndSelectiveDeepExtractSuite
# [POS] Unified facade suite for 2-stage search triage, selective deep extract, budget governance, and coalescing cache

"""Unified facade suite orchestrating two-stage search triage and selective deep extraction."""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.two_stage_search_extract.deep_extract_cleaner import (
    SelectiveDeepExtractCleaner,
)
from myrm_agent_harness.agent.context_management.two_stage_search_extract.fetch_budget_governor import (
    FetchBudgetGovernor,
)
from myrm_agent_harness.agent.context_management.two_stage_search_extract.search_extract_types import (
    DeepExtractResult,
    FetchBudgetStatus,
    SnippetTriageResult,
    TwoStageSearchConfig,
)
from myrm_agent_harness.agent.context_management.two_stage_search_extract.session_coalescing_cache import (
    CacheStats,
    SearchFetchSessionCache,
)
from myrm_agent_harness.agent.context_management.two_stage_search_extract.snippet_triage_engine import (
    RankedSnippetTriageEngine,
)


class TwoStageRankedSnippetAndSelectiveDeepExtractSuite:
    """Production suite providing two-stage search triage and budget-governed deep extraction.

    Protects context windows from explosive token inflation (from 50K tokens down to <500 tokens),
    enforces concurrency and depth budgets, cleans HTML boilerplate noise into dense markdown,
    and coalesces queries within session lifecycles.
    """

    def __init__(
        self,
        config: TwoStageSearchConfig | None = None,
        triage_engine: RankedSnippetTriageEngine | None = None,
        cleaner: SelectiveDeepExtractCleaner | None = None,
        session_cache: SearchFetchSessionCache | None = None,
        budget_governor: FetchBudgetGovernor | None = None,
    ) -> None:
        self._config = config or TwoStageSearchConfig()
        self._triage_engine = triage_engine or RankedSnippetTriageEngine(self._config)
        self._cleaner = cleaner or SelectiveDeepExtractCleaner()
        self._cache = session_cache or SearchFetchSessionCache(
            ttl_seconds=self._config.cache_ttl_seconds
        )
        self._governor = budget_governor or FetchBudgetGovernor(self._config)

    @property
    def config(self) -> TwoStageSearchConfig:
        """Return the configuration parameters."""
        return self._config

    @property
    def cache(self) -> SearchFetchSessionCache:
        """Return the underlying session coalescing cache."""
        return self._cache

    @property
    def governor(self) -> FetchBudgetGovernor:
        """Return the underlying budget governor."""
        return self._governor

    def triage_search_candidates(
        self,
        query: str,
        raw_candidates: list[dict[str, str | float]],
        bypass_cache: bool = False,
    ) -> SnippetTriageResult:
        """Execute Stage 1: Prune search candidates into compact, budget-capped snippets."""
        cached_result = self._cache.get_triage(query, bypass_cache=bypass_cache)
        if cached_result is not None:
            return cached_result

        result = self._triage_engine.triage_candidates(query, raw_candidates)
        self._cache.put_triage(query, result)
        return result

    def selective_deep_extract(
        self,
        url: str,
        title: str,
        raw_content: str,
        session_id: str,
        bypass_cache: bool = False,
    ) -> DeepExtractResult:
        """Execute Stage 2: Cleanse selected web document under concurrency and depth limits."""
        # 1. Authorize fetch against session budget
        self._governor.check_and_authorize_fetches(
            session_id=session_id,
            requested_count=1,
        )

        # 2. Check session cache
        cached_extract = self._cache.get_extract(url, bypass_cache=bypass_cache)
        if cached_extract is not None:
            self._governor.commit_turn_fetches(session_id, performed_count=0)
            return cached_extract

        # 3. Cleanse content and format into dense markdown
        status = self._governor.get_status(session_id)
        current_turn = status.accumulated_fetches + 1
        cleaned_result = self._cleaner.clean_raw_html_or_text(
            url=url,
            title=title,
            raw_content=raw_content,
            fetch_turn=current_turn,
        )

        # 4. Cache and commit budget
        self._cache.put_extract(url, cleaned_result)
        self._governor.commit_turn_fetches(session_id, performed_count=1)

        return cleaned_result

    def batch_deep_extract(
        self,
        targets: list[tuple[str, str, str]],
        session_id: str,
        bypass_cache: bool = False,
    ) -> list[DeepExtractResult]:
        """Execute Stage 2 on a batch of URLs, strictly capping at max concurrency (2 URLs)."""
        requested_count = len(targets)
        self._governor.check_and_authorize_fetches(
            session_id=session_id,
            requested_count=requested_count,
        )

        results: list[DeepExtractResult] = []
        for url, title, raw_content in targets:
            extract = self.selective_deep_extract(
                url=url,
                title=title,
                raw_content=raw_content,
                session_id=session_id,
                bypass_cache=bypass_cache,
            )
            results.append(extract)

        return results

    def get_budget_status(self, session_id: str) -> FetchBudgetStatus:
        """Query the budget and interim synthesis requirements for a session."""
        return self._governor.get_status(session_id)

    def acknowledge_interim_synthesis(self, session_id: str) -> None:
        """Acknowledge that model produced an interim synthesis, resetting consecutive turns."""
        self._governor.reset_consecutive_turns(session_id)

    def get_cache_stats(self) -> CacheStats:
        """Retrieve cache hit and miss telemetry."""
        return self._cache.get_stats()

    def clear_cache(self) -> None:
        """Clear the shared session cache."""
        self._cache.clear()
