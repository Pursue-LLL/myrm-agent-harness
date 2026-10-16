"""Test WebSearchMetrics counters, including per-provider quota tracking."""

from __future__ import annotations

import concurrent.futures

from myrm_agent_harness.toolkits.web_search.core.metrics import WebSearchMetrics


class TestSearchQuotaMetrics:
    """Tests for WebSearchMetrics provider-specific quota tracking."""

    def test_record_provider_search_success_and_failures(self) -> None:
        metrics = WebSearchMetrics()
        metrics.record_provider_search("tavily", success=True, quota_exceeded=False)
        metrics.record_provider_search("tavily", success=True, quota_exceeded=False)
        metrics.record_provider_search("tavily", success=False, quota_exceeded=True)
        metrics.record_provider_search("brave", success=True, quota_exceeded=False)

        snap = metrics.snapshot()
        provider_attempts = snap.get("provider_attempts")
        provider_successes = snap.get("provider_successes")
        provider_quota_exceeded = snap.get("provider_quota_exceeded")

        assert isinstance(provider_attempts, dict)
        assert isinstance(provider_successes, dict)
        assert isinstance(provider_quota_exceeded, dict)

        assert provider_attempts.get("tavily") == 3
        assert provider_successes.get("tavily") == 2
        assert provider_quota_exceeded.get("tavily") == 1

        assert provider_attempts.get("brave") == 1
        assert provider_successes.get("brave") == 1
        assert provider_quota_exceeded.get("brave", 0) == 0

    def test_all_base_metric_counters(self) -> None:
        """Verify all baseline WebSearchMetrics counters."""
        metrics = WebSearchMetrics()
        metrics.record_attempt()
        metrics.record_success()
        metrics.record_terminal_failure()
        metrics.record_retry_scheduled()
        metrics.record_reranker_degraded()
        metrics.record_fallback_triggered()
        metrics.record_fallback_success()
        metrics.record_fallback_failure()
        metrics.record_chain_hop(from_provider="tavily", to_provider="brave")

        snap = metrics.snapshot()
        assert snap["search_attempts"] == 1
        assert snap["search_successes"] == 1
        assert snap["search_terminal_failures"] == 1
        assert snap["search_retry_scheduled"] == 1
        assert snap["reranker_degraded_count"] == 1
        assert snap["fallback_triggered_count"] == 1
        assert snap["fallback_successes"] == 1
        assert snap["fallback_failures"] == 1
        assert snap["chain_hop_count"] == 1

    def test_concurrent_provider_recording_thread_safety(self) -> None:
        """Verify thread-safety when multiple worker threads record searches concurrently."""
        metrics = WebSearchMetrics()
        num_threads = 8
        ops_per_thread = 50

        def worker(provider_name: str) -> None:
            for i in range(ops_per_thread):
                metrics.record_provider_search(
                    provider_name,
                    success=(i % 2 == 0),
                    quota_exceeded=(i == 49),
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, "tavily" if i % 2 == 0 else "brave") for i in range(num_threads)]
            concurrent.futures.wait(futures)

        snap = metrics.snapshot()
        attempts = snap["provider_attempts"]
        assert attempts["tavily"] == (num_threads // 2) * ops_per_thread
        assert attempts["brave"] == (num_threads // 2) * ops_per_thread
